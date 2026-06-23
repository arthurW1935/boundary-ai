from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from armoriq_api.audit import AuditLogger
from armoriq_api.config import Settings
from armoriq_api.llm import BasePlanner
from armoriq_api.mcp_manager import MCPManager
from armoriq_api.models import ApprovalRequest, Conversation, MCPServer, Message, Policy, Run
from armoriq_api.policy import PolicyEngine
from armoriq_api.schemas import ChatResponse
from armoriq_api.types import ToolCall, ToolExecutionIntent


class AgentRuntime:
    def __init__(
        self,
        settings: Settings,
        planner: BasePlanner,
        mcp_manager: MCPManager,
        policy_engine: PolicyEngine,
        audit_logger: AuditLogger,
    ) -> None:
        self.settings = settings
        self.planner = planner
        self.mcp_manager = mcp_manager
        self.policy_engine = policy_engine
        self.audit_logger = audit_logger

    async def handle_chat(self, session: AsyncSession, user_message: str, conversation_id: str | None) -> ChatResponse:
        conversation = await self._get_or_create_conversation(session, conversation_id)
        run = Run(conversation_id=conversation.id, status="running")
        session.add(run)
        session.add(Message(conversation_id=conversation.id, role="user", content=user_message))
        await session.flush()

        await self.audit_logger.record(
            session,
            "chat.user_message",
            {"conversation_id": conversation.id, "message": user_message},
            conversation_id=conversation.id,
            run_id=run.id,
        )

        tools = await self.mcp_manager.list_tools(session, refresh=True)
        await self.audit_logger.record(
            session,
            "mcp.tools_discovered",
            {"count": len(tools), "tools": [asdict(tool) for tool in tools]},
            conversation_id=conversation.id,
            run_id=run.id,
        )

        try:
            plan = await self.planner.plan(user_message, tools)
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            run.latest_response = str(exc)
            await self.audit_logger.record(
                session,
                "agent.planner_error",
                {"error": str(exc)},
                conversation_id=conversation.id,
                run_id=run.id,
            )
            await session.commit()
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="failed",
                assistant_message=f"Planner error: {exc}",
            )

        conversation.spent_tokens += plan.usage_tokens
        conversation.spent_cost += plan.usage_cost

        if plan.tool_call is None:
            assistant_message = plan.assistant_message or "No tool call was required."
            session.add(Message(conversation_id=conversation.id, role="assistant", content=assistant_message))
            run.status = "completed"
            run.latest_response = assistant_message
            await self.audit_logger.record(
                session,
                "agent.response",
                {"message": assistant_message},
                conversation_id=conversation.id,
                run_id=run.id,
            )
            await session.commit()
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="completed",
                assistant_message=assistant_message,
            )

        tool_response = await self._execute_tool_call(session, conversation, run, user_message, plan.tool_call)
        await session.commit()
        return tool_response

    async def decide_approval(
        self,
        session: AsyncSession,
        approval_id: str,
        decision: str,
        comment: str | None,
    ) -> ChatResponse:
        approval = await session.get(ApprovalRequest, approval_id)
        if approval is None:
            raise ValueError("Approval request not found.")
        if approval.status != "pending":
            raise ValueError("Approval request is no longer pending.")

        run = await session.get(Run, approval.run_id)
        conversation = await session.get(Conversation, approval.conversation_id)
        if run is None or conversation is None:
            raise ValueError("Approval request is missing its run context.")

        if approval.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            approval.status = "expired"
            run.status = "denied"
            run.latest_response = "Approval expired before anyone reviewed it."
            session.add(Message(conversation_id=conversation.id, role="assistant", content=run.latest_response))
            await self.audit_logger.record(
                session,
                "approval.expired",
                {"approval_request_id": approval.id},
                conversation_id=conversation.id,
                run_id=run.id,
            )
            await session.commit()
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="denied",
                assistant_message=run.latest_response,
                approval_request_id=approval.id,
            )

        approval.status = decision
        approval.decision_comment = comment
        approval.decided_at = datetime.utcnow()
        await self.audit_logger.record(
            session,
            f"approval.{decision}",
            {"approval_request_id": approval.id, "comment": comment},
            conversation_id=conversation.id,
            run_id=run.id,
        )

        if decision == "denied":
            run.status = "denied"
            run.latest_response = "Tool call denied by human approval."
            session.add(Message(conversation_id=conversation.id, role="assistant", content=run.latest_response))
            await session.commit()
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="denied",
                assistant_message=run.latest_response,
                approval_request_id=approval.id,
            )

        run.status = "running"
        tool_call = ToolCall(server_id=approval.server_id, tool_name=approval.tool_name, arguments=approval.arguments_json)
        response = await self._run_allowed_tool(session, conversation, run, "approved tool execution", tool_call)
        await session.commit()
        return response

    async def _execute_tool_call(
        self,
        session: AsyncSession,
        conversation: Conversation,
        run: Run,
        user_message: str,
        tool_call: ToolCall,
    ) -> ChatResponse:
        server = await session.get(MCPServer, tool_call.server_id)
        if server is None:
            run.status = "failed"
            run.latest_response = "Selected MCP server could not be found."
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="failed",
                assistant_message=run.latest_response,
            )

        intent = ToolExecutionIntent(
            conversation_id=conversation.id,
            run_id=run.id,
            server_id=server.id,
            server_name=server.name,
            tool_name=tool_call.tool_name,
            arguments=tool_call.arguments,
            token_budget=conversation.token_budget,
            cost_budget=conversation.cost_budget,
            spent_tokens=conversation.spent_tokens,
            spent_cost=conversation.spent_cost,
        )
        policies = (await session.scalars(select(Policy).where(Policy.enabled.is_(True)))).all()
        decision = self.policy_engine.evaluate(intent, policies)
        await self.audit_logger.record(
            session,
            "policy.decision",
            {
                "tool_name": tool_call.tool_name,
                "server_id": tool_call.server_id,
                "arguments": tool_call.arguments,
                "verdict": decision.verdict,
                "reason": decision.reason,
                "matched_rule_ids": decision.matched_rule_ids,
            },
            conversation_id=conversation.id,
            run_id=run.id,
        )

        if decision.verdict == "block":
            assistant_message = f"Tool call blocked: {decision.reason}"
            session.add(Message(conversation_id=conversation.id, role="assistant", content=assistant_message))
            run.status = "blocked"
            run.latest_response = assistant_message
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="blocked",
                assistant_message=assistant_message,
                tool_call={"server_id": tool_call.server_id, "tool_name": tool_call.tool_name, "arguments": tool_call.arguments},
            )

        if decision.verdict == "require_approval":
            approval = ApprovalRequest(
                run_id=run.id,
                conversation_id=conversation.id,
                server_id=tool_call.server_id,
                tool_name=tool_call.tool_name,
                arguments_json=tool_call.arguments,
                status="pending",
                reason=decision.reason,
                expires_at=datetime.utcnow() + timedelta(seconds=self.settings.approval_ttl_seconds),
            )
            session.add(approval)
            await session.flush()
            run.status = "waiting_approval"
            run.paused_reason = decision.reason
            assistant_message = f"Tool call requires approval: {decision.reason}"
            session.add(Message(conversation_id=conversation.id, role="assistant", content=assistant_message))
            await self.audit_logger.record(
                session,
                "approval.requested",
                {
                    "approval_request_id": approval.id,
                    "tool_name": tool_call.tool_name,
                    "reason": decision.reason,
                },
                conversation_id=conversation.id,
                run_id=run.id,
            )
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="waiting_approval",
                assistant_message=assistant_message,
                tool_call={"server_id": tool_call.server_id, "tool_name": tool_call.tool_name, "arguments": tool_call.arguments},
                approval_request_id=approval.id,
            )

        return await self._run_allowed_tool(session, conversation, run, user_message, tool_call)

    async def _run_allowed_tool(
        self,
        session: AsyncSession,
        conversation: Conversation,
        run: Run,
        user_message: str,
        tool_call: ToolCall,
    ) -> ChatResponse:
        try:
            tool_result = await self.mcp_manager.call_tool(session, tool_call.server_id, tool_call.tool_name, tool_call.arguments)
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            run.latest_response = f"Tool execution failed: {exc}"
            session.add(Message(conversation_id=conversation.id, role="assistant", content=run.latest_response))
            await self.audit_logger.record(
                session,
                "mcp.tool_failed",
                {"tool_name": tool_call.tool_name, "error": str(exc)},
                conversation_id=conversation.id,
                run_id=run.id,
            )
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="failed",
                assistant_message=run.latest_response,
                tool_call={"server_id": tool_call.server_id, "tool_name": tool_call.tool_name, "arguments": tool_call.arguments},
            )

        session.add(
            Message(
                conversation_id=conversation.id,
                role="tool",
                content=str(tool_result),
                metadata_json={"tool_name": tool_call.tool_name, "server_id": tool_call.server_id},
            )
        )
        await self.audit_logger.record(
            session,
            "mcp.tool_succeeded",
            {"tool_name": tool_call.tool_name, "result": tool_result},
            conversation_id=conversation.id,
            run_id=run.id,
        )

        summary = await self.planner.summarize_tool_result(user_message, tool_call, tool_result)
        conversation.spent_tokens += summary.usage_tokens
        conversation.spent_cost += summary.usage_cost
        assistant_message = summary.assistant_message or "Tool execution completed."
        session.add(Message(conversation_id=conversation.id, role="assistant", content=assistant_message))
        run.status = "completed"
        run.paused_reason = None
        run.latest_response = assistant_message
        await self.audit_logger.record(
            session,
            "agent.response",
            {"message": assistant_message},
            conversation_id=conversation.id,
            run_id=run.id,
        )
        return ChatResponse(
            conversation_id=conversation.id,
            run_id=run.id,
            status="completed",
            assistant_message=assistant_message,
            tool_call={"server_id": tool_call.server_id, "tool_name": tool_call.tool_name, "arguments": tool_call.arguments},
        )

    async def _get_or_create_conversation(self, session: AsyncSession, conversation_id: str | None) -> Conversation:
        if conversation_id:
            conversation = await session.get(Conversation, conversation_id)
            if conversation:
                return conversation
        conversation = Conversation()
        session.add(conversation)
        await session.flush()
        return conversation
