from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from armoriq_api.agent import AgentRuntime
from armoriq_api.audit import AuditLogger
from armoriq_api.config import get_settings
from armoriq_api.db import get_session, init_db
from armoriq_api.llm import get_planner
from armoriq_api.mcp_manager import MCPManager
from armoriq_api.models import ApprovalRequest, AuditEvent, Conversation, MCPServer, Message, Policy
from armoriq_api.policy import PolicyEngine
from armoriq_api.realtime import EventBroker
from armoriq_api.schemas import ApprovalDecisionRequest, ChatRequest, MCPServerCreate, MCPServerUpdate, PolicyCreate, PolicyUpdate


settings = get_settings()
broker = EventBroker(settings.redis_url)
audit_logger = AuditLogger(broker)
mcp_manager = MCPManager()
policy_engine = PolicyEngine()
agent_runtime = AgentRuntime(settings, get_planner(settings), mcp_manager, policy_engine, audit_logger)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await broker.connect()
    async for session in get_session():
        await mcp_manager.ensure_seed_servers(
            session,
            python_executable=sys.executable,
            remote_url=settings.remote_mcp_url,
            remote_transport=settings.remote_mcp_transport,
            remote_name=settings.remote_mcp_name,
        )
        await mcp_manager.list_tools(session, refresh=True)
        await session.commit()
        break
    yield
    await broker.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/conversations")
async def list_conversations(session: AsyncSession = Depends(get_session)) -> list[dict]:
    conversations = (await session.scalars(select(Conversation).order_by(Conversation.created_at.desc()))).all()
    return [
        {
            "id": conversation.id,
            "title": conversation.title,
            "token_budget": conversation.token_budget,
            "cost_budget": conversation.cost_budget,
            "spent_tokens": conversation.spent_tokens,
            "spent_cost": conversation.spent_cost,
            "created_at": conversation.created_at,
        }
        for conversation in conversations
    ]


@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: str, session: AsyncSession = Depends(get_session)) -> list[dict]:
    messages = (
        await session.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
        )
    ).all()
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "metadata": message.metadata_json,
            "created_at": message.created_at,
        }
        for message in messages
    ]


@app.post("/api/chat")
async def chat(payload: ChatRequest, session: AsyncSession = Depends(get_session)):
    return await agent_runtime.handle_chat(session, payload.message, payload.conversation_id)


@app.get("/api/mcp/servers")
async def list_mcp_servers(session: AsyncSession = Depends(get_session)) -> list[dict]:
    servers = (
        await session.scalars(select(MCPServer).options(selectinload(MCPServer.tools)).order_by(MCPServer.name.asc()))
    ).all()
    return [
        {
            "id": server.id,
            "name": server.name,
            "transport": server.transport,
            "enabled": server.enabled,
            "config": server.config_json,
            "last_error": server.last_error,
            "last_discovered_at": server.last_discovered_at,
            "tool_count": len(server.tools),
        }
        for server in servers
    ]


@app.post("/api/mcp/servers")
async def create_mcp_server(payload: MCPServerCreate, session: AsyncSession = Depends(get_session)) -> dict:
    server = MCPServer(
        name=payload.name,
        transport=payload.transport,
        enabled=payload.enabled,
        config_json=payload.config,
    )
    session.add(server)
    await session.flush()
    await audit_logger.record(session, "mcp.server_created", {"server_id": server.id, "name": server.name})
    await session.commit()
    return {"id": server.id}


@app.patch("/api/mcp/servers/{server_id}")
async def update_mcp_server(server_id: str, payload: MCPServerUpdate, session: AsyncSession = Depends(get_session)) -> dict:
    server = await session.get(MCPServer, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if payload.enabled is not None:
        server.enabled = payload.enabled
    if payload.config is not None:
        server.config_json = payload.config
    await audit_logger.record(
        session,
        "mcp.server_updated",
        {"server_id": server.id, "enabled": server.enabled},
    )
    await session.commit()
    return {"ok": True}


@app.post("/api/mcp/servers/{server_id}/refresh")
async def refresh_mcp_server(server_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    server = await session.get(MCPServer, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    try:
        tools = await mcp_manager.refresh_server_tools(session, server)
        await audit_logger.record(
            session,
            "mcp.server_refreshed",
            {"server_id": server.id, "tool_count": len(tools)},
        )
        await session.commit()
        return {"tool_count": len(tools)}
    except Exception as exc:  # noqa: BLE001
        server.last_error = str(exc)
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/mcp/tools")
async def list_mcp_tools(session: AsyncSession = Depends(get_session)) -> list[dict]:
    tools = await mcp_manager.list_tools(session, refresh=False)
    return [
        {
            "server_id": tool.server_id,
            "server_name": tool.server_name,
            "transport": tool.transport,
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


@app.get("/api/policies")
async def list_policies(session: AsyncSession = Depends(get_session)) -> list[dict]:
    policies = (await session.scalars(select(Policy).order_by(Policy.priority.desc(), Policy.created_at.desc()))).all()
    return [
        {
            "id": policy.id,
            "name": policy.name,
            "rule_type": policy.rule_type,
            "enabled": policy.enabled,
            "priority": policy.priority,
            "target_tool": policy.target_tool,
            "target_server_id": policy.target_server_id,
            "conditions": policy.conditions_json,
            "action": policy.action_json,
            "created_at": policy.created_at,
        }
        for policy in policies
    ]


@app.post("/api/policies")
async def create_policy(payload: PolicyCreate, session: AsyncSession = Depends(get_session)) -> dict:
    policy = Policy(
        name=payload.name,
        rule_type=payload.rule_type,
        enabled=payload.enabled,
        priority=payload.priority,
        target_tool=payload.target_tool,
        target_server_id=payload.target_server_id,
        conditions_json=payload.conditions,
        action_json=payload.action,
    )
    session.add(policy)
    await session.flush()
    await audit_logger.record(
        session,
        "policy.created",
        {"policy_id": policy.id, "name": policy.name, "rule_type": policy.rule_type},
    )
    await session.commit()
    return {"id": policy.id}


@app.patch("/api/policies/{policy_id}")
async def update_policy(policy_id: str, payload: PolicyUpdate, session: AsyncSession = Depends(get_session)) -> dict:
    policy = await session.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        if field_name == "conditions":
            policy.conditions_json = value
        elif field_name == "action":
            policy.action_json = value
        else:
            setattr(policy, field_name, value)
    await audit_logger.record(
        session,
        "policy.updated",
        {"policy_id": policy.id, "enabled": policy.enabled, "priority": policy.priority},
    )
    await session.commit()
    return {"ok": True}


@app.delete("/api/policies/{policy_id}")
async def delete_policy(policy_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    policy = await session.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    await audit_logger.record(session, "policy.deleted", {"policy_id": policy.id})
    await session.delete(policy)
    await session.commit()
    return {"ok": True}


@app.get("/api/approvals")
async def list_approvals(session: AsyncSession = Depends(get_session)) -> list[dict]:
    approvals = (await session.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()))).all()
    return [
        {
            "id": approval.id,
            "run_id": approval.run_id,
            "conversation_id": approval.conversation_id,
            "server_id": approval.server_id,
            "tool_name": approval.tool_name,
            "arguments": approval.arguments_json,
            "status": approval.status,
            "reason": approval.reason,
            "expires_at": approval.expires_at,
            "comment": approval.decision_comment,
            "created_at": approval.created_at,
        }
        for approval in approvals
    ]


@app.post("/api/approvals/{approval_id}/decision")
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await agent_runtime.decide_approval(session, approval_id, payload.decision, payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/logs")
async def list_logs(session: AsyncSession = Depends(get_session), limit: int = 100) -> list[dict]:
    events = (await session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit))).all()
    return [
        {
            "id": event.id,
            "conversation_id": event.conversation_id,
            "run_id": event.run_id,
            "event_type": event.event_type,
            "payload": event.payload_json,
            "created_at": event.created_at,
        }
        for event in events
    ]


@app.get("/api/events/stream")
async def stream_events(request: Request):
    async def event_generator():
        async with broker.subscribe() as queue:
            yield {"event": "ready", "data": json.dumps({"message": "connected"})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield {"event": event["type"], "data": json.dumps(event, default=str)}
                except TimeoutError:
                    yield {"event": "ping", "data": json.dumps({"ts": "keepalive"})}

    return EventSourceResponse(event_generator())
