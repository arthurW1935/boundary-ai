from __future__ import annotations

import json
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
from armoriq_api.types import ExecutedToolStep, ToolCall, ToolExecutionIntent


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
        conversation = await self._get_or_create_conversation(session, conversation_id, user_message)
        pending_approval = None
        if conversation_id:
            pending_approval = await session.scalar(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.conversation_id == conversation.id,
                    ApprovalRequest.status == "pending",
                )
                .order_by(ApprovalRequest.created_at.desc())
                .limit(1)
            )
        if pending_approval is not None:
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=pending_approval.run_id,
                status="waiting_approval",
                assistant_message=f"Conversation is waiting for approval: {pending_approval.reason}",
                approval_request_id=pending_approval.id,
            )

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

        tools = await self.mcp_manager.list_tools(session, refresh=False)
        await self.audit_logger.record(
            session,
            "mcp.tools_discovered",
            {"count": len(tools), "tools": [asdict(tool) for tool in tools]},
            conversation_id=conversation.id,
            run_id=run.id,
        )

        response = await self._run_planner_loop(session, conversation, run, user_message, tools, [])
        await session.commit()
        return response

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
        stored_context = self._extract_approval_context(approval.arguments_json)
        executed_steps = [self._executed_step_from_dict(item) for item in stored_context["executed_steps"]]
        tool_call = ToolCall(
            server_id=approval.server_id,
            tool_name=approval.tool_name,
            arguments=stored_context["tool_arguments"],
        )
        tools = await self.mcp_manager.list_tools(session, refresh=False)
        step_result = await self._execute_allowed_tool_step(
            session,
            conversation,
            run,
            tool_call,
            executed_steps,
        )
        if isinstance(step_result, ChatResponse):
            await session.commit()
            return step_result

        executed_steps.append(step_result)
        response = await self._run_planner_loop(
            session,
            conversation,
            run,
            stored_context["user_message"],
            tools,
            executed_steps,
        )
        await session.commit()
        return response

    async def _run_planner_loop(
        self,
        session: AsyncSession,
        conversation: Conversation,
        run: Run,
        user_message: str,
        tools: list,
        executed_steps: list[ExecutedToolStep],
    ) -> ChatResponse:
        for _ in range(self.settings.max_tool_steps):
            try:
                plan = await self.planner.plan(user_message, tools, executed_steps)
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
                return ChatResponse(
                    conversation_id=conversation.id,
                    run_id=run.id,
                    status="failed",
                    assistant_message=f"Planner error: {exc}",
                    executed_tool_calls=self._serialize_steps(executed_steps),
                )

            conversation.spent_tokens += plan.usage_tokens
            conversation.spent_cost += plan.usage_cost

            if plan.tool_call is None:
                assistant_message = plan.assistant_message or self._fallback_summary(executed_steps)
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
                    executed_tool_calls=self._serialize_steps(executed_steps),
                )

            tool_response = await self._evaluate_tool_call(
                session,
                conversation,
                run,
                user_message,
                plan.tool_call,
                executed_steps,
            )
            if isinstance(tool_response, ChatResponse):
                return tool_response
            executed_steps.append(tool_response)

        assistant_message = "Stopped after reaching the maximum number of tool steps for this run."
        session.add(Message(conversation_id=conversation.id, role="assistant", content=assistant_message))
        run.status = "failed"
        run.latest_response = assistant_message
        await self.audit_logger.record(
            session,
            "agent.max_steps_reached",
            {"max_tool_steps": self.settings.max_tool_steps},
            conversation_id=conversation.id,
            run_id=run.id,
        )
        return ChatResponse(
            conversation_id=conversation.id,
            run_id=run.id,
            status="failed",
            assistant_message=assistant_message,
            executed_tool_calls=self._serialize_steps(executed_steps),
        )

    async def _evaluate_tool_call(
        self,
        session: AsyncSession,
        conversation: Conversation,
        run: Run,
        user_message: str,
        tool_call: ToolCall,
        executed_steps: list[ExecutedToolStep],
    ) -> ChatResponse | ExecutedToolStep:
        server = await session.get(MCPServer, tool_call.server_id)
        if server is None:
            run.status = "failed"
            run.latest_response = "Selected MCP server could not be found."
            return ChatResponse(
                conversation_id=conversation.id,
                run_id=run.id,
                status="failed",
                assistant_message=run.latest_response,
                executed_tool_calls=self._serialize_steps(executed_steps),
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
                tool_call=self._serialize_tool_call(tool_call),
                executed_tool_calls=self._serialize_steps(executed_steps),
            )

        if decision.verdict == "require_approval":
            approval = ApprovalRequest(
                run_id=run.id,
                conversation_id=conversation.id,
                server_id=tool_call.server_id,
                tool_name=tool_call.tool_name,
                arguments_json=self._build_approval_context(tool_call, user_message, executed_steps),
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
                tool_call=self._serialize_tool_call(tool_call),
                executed_tool_calls=self._serialize_steps(executed_steps),
                approval_request_id=approval.id,
            )

        return await self._execute_allowed_tool_step(session, conversation, run, tool_call, executed_steps)

    async def _execute_allowed_tool_step(
        self,
        session: AsyncSession,
        conversation: Conversation,
        run: Run,
        tool_call: ToolCall,
        executed_steps: list[ExecutedToolStep],
    ) -> ChatResponse | ExecutedToolStep:
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
                tool_call=self._serialize_tool_call(tool_call),
                executed_tool_calls=self._serialize_steps(executed_steps),
            )

        session.add(
            Message(
                conversation_id=conversation.id,
                role="tool",
                content=json.dumps(tool_result, indent=2),
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
        return ExecutedToolStep(
            tool_call=tool_call,
            result=tool_result,
            is_error=bool(tool_result.get("raw", {}).get("isError")) if isinstance(tool_result, dict) else False,
        )

    async def _get_or_create_conversation(
        self,
        session: AsyncSession,
        conversation_id: str | None,
        user_message: str,
    ) -> Conversation:
        if conversation_id:
            conversation = await session.get(Conversation, conversation_id)
            if conversation:
                return conversation
        title = user_message.strip().splitlines()[0][:60] or "New conversation"
        conversation = Conversation(title=title)
        session.add(conversation)
        await session.flush()
        return conversation

    def _serialize_tool_call(self, tool_call: ToolCall) -> dict[str, Any]:
        return {
            "server_id": tool_call.server_id,
            "tool_name": tool_call.tool_name,
            "arguments": tool_call.arguments,
        }

    def _serialize_steps(self, executed_steps: list[ExecutedToolStep]) -> list[dict[str, Any]]:
        return [
            {
                "server_id": step.tool_call.server_id,
                "tool_name": step.tool_call.tool_name,
                "arguments": step.tool_call.arguments,
                "result": step.result,
                "is_error": step.is_error,
            }
            for step in executed_steps
        ]

    def _fallback_summary(self, executed_steps: list[ExecutedToolStep]) -> str:
        if not executed_steps:
            return "No tool call was required."
        return "Completed the requested tool actions."

    def _build_approval_context(
        self,
        tool_call: ToolCall,
        user_message: str,
        executed_steps: list[ExecutedToolStep],
    ) -> dict[str, Any]:
        return {
            "__tool_arguments__": tool_call.arguments,
            "__user_message__": user_message,
            "__executed_steps__": self._serialize_steps(executed_steps),
        }

    def _extract_approval_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool_arguments = payload.get("__tool_arguments__", payload)
        return {
            "tool_arguments": tool_arguments,
            "user_message": payload.get("__user_message__", "approved tool execution"),
            "executed_steps": payload.get("__executed_steps__", []),
        }

    def _executed_step_from_dict(self, payload: dict[str, Any]) -> ExecutedToolStep:
        return ExecutedToolStep(
            tool_call=ToolCall(
                server_id=payload["server_id"],
                tool_name=payload["tool_name"],
                arguments=payload.get("arguments", {}),
            ),
            result=payload.get("result", {}),
            is_error=payload.get("is_error", False),
        )
