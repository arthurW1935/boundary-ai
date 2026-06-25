from __future__ import annotations

import json
import re
from typing import Any

import httpx

from armoriq_api.config import Settings
from armoriq_api.types import ExecutedToolStep, PlannerDecision, PlannerMessage, ToolCall, ToolDescriptor


class BasePlanner:
    async def plan(
        self,
        user_message: str,
        tools: list[ToolDescriptor],
        executed_steps: list[ExecutedToolStep],
        conversation_history: list[PlannerMessage],
    ) -> PlannerDecision:
        raise NotImplementedError


class MissingPlanner(BasePlanner):
    def __init__(self, message: str) -> None:
        self.message = message

    async def plan(
        self,
        user_message: str,
        tools: list[ToolDescriptor],
        executed_steps: list[ExecutedToolStep],
        conversation_history: list[PlannerMessage],
    ) -> PlannerDecision:
        raise RuntimeError(self.message)


class MockPlanner(BasePlanner):
    async def plan(
        self,
        user_message: str,
        tools: list[ToolDescriptor],
        executed_steps: list[ExecutedToolStep],
        conversation_history: list[PlannerMessage],
    ) -> PlannerDecision:
        actions = self._parse_actions(user_message, tools)
        if not actions:
            follow_up = self._answer_follow_up(user_message, conversation_history)
            if follow_up is not None:
                return PlannerDecision(assistant_message=follow_up)
            available = ", ".join(f"{tool.server_name}:{tool.name}" for tool in tools) or "no tools discovered"
            return PlannerDecision(
                assistant_message=(
                    "I can help once you ask for a concrete file action. "
                    f"Currently discovered tools: {available}."
                )
            )

        if len(executed_steps) < len(actions):
            return PlannerDecision(assistant_message=None, tool_call=actions[len(executed_steps)])

        lines = []
        for step in executed_steps:
            lines.append(
                f"- {step.tool_call.tool_name}({json.dumps(step.tool_call.arguments)}) -> "
                f"{json.dumps(step.result, ensure_ascii=True)}"
            )
        return PlannerDecision(
            assistant_message="Completed the requested tool actions:\n" + "\n".join(lines)
        )

    def _answer_follow_up(self, user_message: str, conversation_history: list[PlannerMessage]) -> str | None:
        normalized = user_message.lower().strip()
        if "why" not in normalized and "blocked" not in normalized and "approval" not in normalized:
            return None

        for message in reversed(conversation_history):
            if message.role != "assistant":
                continue
            if message.content.startswith("Tool call blocked:"):
                reason = message.content.split(":", maxsplit=1)[1].strip()
                return f"Your last tool call was blocked because: {reason}"
            if message.content.startswith("Tool call requires approval:"):
                reason = message.content.split(":", maxsplit=1)[1].strip()
                return f"Your last tool call needs approval because: {reason}"

        return None

    def _parse_actions(self, user_message: str, tools: list[ToolDescriptor]) -> list[ToolCall]:
        actions: list[ToolCall] = []
        segments = [segment.strip() for segment in re.split(r"[\r\n]+", user_message) if segment.strip()]
        if len(segments) == 1:
            segments = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", user_message) if segment.strip()]

        for segment in segments:
            lower = segment.lower().strip()
            if "web search" in lower or "search web" in lower or "search the web" in lower:
                tool = self._pick_tool(tools, lambda name: "web_search_exa" == name)
                if tool is None:
                    continue
                query = self._extract_web_query(segment)
                actions.append(
                    ToolCall(
                        server_id=tool.server_id,
                        tool_name=tool.name,
                        arguments={"query": query, "numResults": 5},
                    )
                )
                continue

            if "list" in lower and "file" in lower:
                tool = self._pick_tool(tools, lambda name: "list" in name and "file" in name)
                if tool is None:
                    continue
                path_match = re.search(r"(?:in|under)\s+([^\s]+)", segment, re.IGNORECASE)
                arguments = {"path": path_match.group(1).strip() if path_match else "."}
                actions.append(ToolCall(server_id=tool.server_id, tool_name=tool.name, arguments=arguments))
                continue

            if "read" in lower and "file" in lower:
                tool = self._pick_tool(tools, lambda name: "read" in name and "file" in name)
                if tool is None:
                    continue
                path = self._extract_path(segment, "read")
                actions.append(ToolCall(server_id=tool.server_id, tool_name=tool.name, arguments={"path": path}))
                continue

            if "write" in lower and "file" in lower:
                tool = self._pick_tool(tools, lambda name: "write" in name and "file" in name)
                if tool is None:
                    continue
                path, content = self._extract_write_parts(segment)
                actions.append(
                    ToolCall(
                        server_id=tool.server_id,
                        tool_name=tool.name,
                        arguments={"path": path, "content": content, "create_dirs": True},
                    )
                )
                continue

            if "delete" in lower and "file" in lower:
                tool = self._pick_tool(tools, lambda name: "delete" in name and "file" in name)
                if tool is None:
                    continue
                path = self._extract_path(segment, "delete")
                actions.append(ToolCall(server_id=tool.server_id, tool_name=tool.name, arguments={"path": path}))
                continue

            if "search" in lower:
                tool = self._pick_tool(tools, lambda name: "search" in name and "file" in name)
                if tool is None:
                    continue
                query = self._extract_search_query(segment)
                actions.append(
                    ToolCall(server_id=tool.server_id, tool_name=tool.name, arguments={"query": query, "path": "."})
                )

        return actions

    def _pick_tool(self, tools: list[ToolDescriptor], predicate) -> ToolDescriptor | None:
        for tool in tools:
            if predicate(tool.name.lower()):
                return tool
        return None

    def _extract_path(self, message: str, verb: str) -> str:
        match = re.search(
            rf"{verb}(?:\s+the)?(?:\s+file)?\s+([^\s]+)",
            message,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError(f"Please provide a path to {verb}.")
        return match.group(1).strip(" .")

    def _extract_write_parts(self, message: str) -> tuple[str, str]:
        match = re.search(
            r"write(?:\s+the)?(?:\s+file)?\s+([^\s:]+)(?::|\s+with content\s+)(.+)",
            message,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise ValueError("Please use `write file <path>: <content>`.")
        return match.group(1).strip(), match.group(2).strip()

    def _extract_search_query(self, message: str) -> str:
        match = re.search(r"search(?:\s+files?)?(?:\s+for)?\s+(.+)", message, re.IGNORECASE)
        if not match:
            raise ValueError("Please provide a query to search for.")
        return match.group(1).strip().strip('"')

    def _extract_web_query(self, message: str) -> str:
        match = re.search(r"(?:web search|search(?:\s+the)?\s+web)(?:\s+for)?\s+(.+)", message, re.IGNORECASE)
        if not match:
            raise ValueError("Please provide a web query.")
        return match.group(1).strip().strip('"')


class OpenAICompatPlanner(BasePlanner):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def plan(
        self,
        user_message: str,
        tools: list[ToolDescriptor],
        executed_steps: list[ExecutedToolStep],
        conversation_history: list[PlannerMessage],
    ) -> PlannerDecision:
        tool_aliases = self._build_tool_aliases(tools)
        payload = {
            "model": self.settings.openai_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a guarded MCP agent. You may call tools sequentially when needed. "
                        "Use as many tool calls as necessary, but stop once you can answer clearly. "
                        "If tool results already answer the question, provide the final answer instead of another tool call. "
                        "When the conversation history already explains a blocked tool call or approval requirement, answer directly and do not claim you lack context."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_user_prompt(user_message, executed_steps, conversation_history),
                },
            ],
            "tool_choice": "auto",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": alias,
                        "description": tool.description or "",
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                    },
                }
                for alias, tool in tool_aliases.items()
            ],
        }

        async with httpx.AsyncClient(base_url=self.settings.openai_base_url, timeout=30.0) as client:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"OpenAI request failed ({response.status_code}): {response.text}"
                ) from exc
            data = response.json()

        message = data["choices"][0]["message"]
        usage = data.get("usage", {})
        if message.get("tool_calls"):
            call = message["tool_calls"][0]
            descriptor = tool_aliases.get(call["function"]["name"])
            if descriptor is None:
                raise RuntimeError(f"OpenAI returned unknown tool alias: {call['function']['name']}")
            arguments = json.loads(call["function"]["arguments"] or "{}")
            return PlannerDecision(
                assistant_message=message.get("content"),
                tool_call=ToolCall(
                    server_id=descriptor.server_id,
                    tool_name=descriptor.name,
                    arguments=arguments,
                ),
                usage_tokens=usage.get("total_tokens", 0),
            )

        return PlannerDecision(
            assistant_message=message.get("content") or "No response returned.",
            usage_tokens=usage.get("total_tokens", 0),
        )

    def _build_user_prompt(
        self,
        user_message: str,
        executed_steps: list[ExecutedToolStep],
        conversation_history: list[PlannerMessage],
    ) -> str:
        sections: list[str] = []

        if conversation_history:
            history_lines = [
                f"{message.role.title()}: {message.content}"
                for message in conversation_history[-8:]
            ]
            sections.append("Recent conversation history:\n" + "\n".join(history_lines))

        if executed_steps:
            step_lines = []
            for index, step in enumerate(executed_steps, start=1):
                step_lines.append(
                    f"Step {index}: {step.tool_call.tool_name} with {json.dumps(step.tool_call.arguments)} "
                    f"returned {json.dumps(step.result)}"
                )
            sections.append("Tool execution history so far:\n" + "\n".join(step_lines))

        sections.append(f"Current user request:\n{user_message}")
        sections.append("Decide whether another tool call is needed or give the final answer.")
        return "\n\n".join(sections)

    def _build_tool_aliases(self, tools: list[ToolDescriptor]) -> dict[str, ToolDescriptor]:
        aliases: dict[str, ToolDescriptor] = {}
        for index, tool in enumerate(tools, start=1):
            server_part = re.sub(r"[^a-zA-Z0-9_-]", "_", tool.server_name)[:16] or "server"
            tool_part = re.sub(r"[^a-zA-Z0-9_-]", "_", tool.name)[:32] or "tool"
            base_alias = f"tool_{index}_{server_part}_{tool_part}"[:64]
            alias = base_alias
            suffix = 2
            while alias in aliases:
                suffix_text = f"_{suffix}"
                alias = f"{base_alias[: 64 - len(suffix_text)]}{suffix_text}"
                suffix += 1
            aliases[alias] = tool
        return aliases


def get_planner(settings: Settings) -> BasePlanner:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return OpenAICompatPlanner(settings)
    if settings.llm_provider == "mock" and settings.allow_demo_mock_planner:
        return MockPlanner()
    return MissingPlanner(
        "No reviewed LLM provider is configured. Set OPENAI_API_KEY for the OpenAI-compatible planner "
        "or explicitly enable ALLOW_DEMO_MOCK_PLANNER=true with LLM_PROVIDER=mock for local-only demos."
    )
