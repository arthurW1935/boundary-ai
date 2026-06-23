from __future__ import annotations

import json
import re
from typing import Any

import httpx

from armoriq_api.config import Settings
from armoriq_api.types import PlannerDecision, ToolCall, ToolDescriptor


class BasePlanner:
    async def plan(self, user_message: str, tools: list[ToolDescriptor]) -> PlannerDecision:
        raise NotImplementedError

    async def summarize_tool_result(
        self,
        user_message: str,
        tool_call: ToolCall,
        tool_result: dict[str, Any],
    ) -> PlannerDecision:
        raise NotImplementedError


class MockPlanner(BasePlanner):
    async def plan(self, user_message: str, tools: list[ToolDescriptor]) -> PlannerDecision:
        lower = user_message.lower().strip()

        tool = self._pick_tool(
            tools,
            lambda name: "list" in name and "file" in name,
            lower,
            default_args={"path": "."},
        )
        if tool:
            if "list" in lower and "file" in lower:
                path_match = re.search(r"(?:in|under)\s+([^\s]+)", lower)
                if path_match:
                    tool.arguments["path"] = path_match.group(1)
                return PlannerDecision(assistant_message=None, tool_call=tool)

        if "read" in lower and "file" in lower:
            tool = self._pick_tool(tools, lambda name: "read" in name and "file" in name, lower)
            if tool:
                path = self._extract_path(lower, "read")
                return PlannerDecision(assistant_message=None, tool_call=ToolCall(tool.server_id, tool.tool_name, {"path": path}))

        if "write" in lower and "file" in lower:
            tool = self._pick_tool(tools, lambda name: "write" in name and "file" in name, lower)
            if tool:
                path, content = self._extract_write_parts(user_message)
                return PlannerDecision(
                    assistant_message=None,
                    tool_call=ToolCall(tool.server_id, tool.tool_name, {"path": path, "content": content, "create_dirs": True}),
                )

        if "delete" in lower and "file" in lower:
            tool = self._pick_tool(tools, lambda name: "delete" in name and "file" in name, lower)
            if tool:
                path = self._extract_path(lower, "delete")
                return PlannerDecision(assistant_message=None, tool_call=ToolCall(tool.server_id, tool.tool_name, {"path": path}))

        if "search" in lower:
            tool = self._pick_tool(tools, lambda name: "search" in name and "file" in name, lower)
            if tool:
                query = self._extract_search_query(user_message)
                return PlannerDecision(assistant_message=None, tool_call=ToolCall(tool.server_id, tool.tool_name, {"query": query, "path": "."}))

        available = ", ".join(f"{tool.server_name}:{tool.name}" for tool in tools) or "no tools discovered"
        return PlannerDecision(
            assistant_message=(
                "I can help once you ask for a concrete file action. "
                f"Currently discovered tools: {available}."
            )
        )

    async def summarize_tool_result(
        self,
        user_message: str,
        tool_call: ToolCall,
        tool_result: dict[str, Any],
    ) -> PlannerDecision:
        summary = json.dumps(tool_result, indent=2)
        return PlannerDecision(
            assistant_message=(
                f"I used `{tool_call.tool_name}` in response to your request and got:\n{summary}"
            )
        )

    def _pick_tool(
        self,
        tools: list[ToolDescriptor],
        predicate,
        message: str,
        default_args: dict[str, Any] | None = None,
    ) -> ToolCall | None:
        for tool in tools:
            if predicate(tool.name.lower()):
                return ToolCall(server_id=tool.server_id, tool_name=tool.name, arguments=default_args or {})
        return None

    def _extract_path(self, message: str, verb: str) -> str:
        match = re.search(rf"{verb}(?:\s+file)?\s+([^\s]+)", message)
        if not match:
            raise ValueError(f"Please provide a path to {verb}.")
        return match.group(1).strip(" .")

    def _extract_write_parts(self, message: str) -> tuple[str, str]:
        match = re.search(r"write(?:\s+file)?\s+([^\s:]+)(?::|\s+with content\s+)(.+)", message, re.IGNORECASE | re.DOTALL)
        if not match:
            raise ValueError("Please use `write file <path>: <content>`.")
        return match.group(1).strip(), match.group(2).strip()

    def _extract_search_query(self, message: str) -> str:
        match = re.search(r"search(?:\s+files?)?(?:\s+for)?\s+(.+)", message, re.IGNORECASE)
        if not match:
            raise ValueError("Please provide a query to search for.")
        return match.group(1).strip().strip('"')


class OpenAICompatPlanner(BasePlanner):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def plan(self, user_message: str, tools: list[ToolDescriptor]) -> PlannerDecision:
        payload = {
            "model": self.settings.openai_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a guarded MCP agent. Choose a tool when it is useful. "
                        "If no tool is needed, answer directly."
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            "tool_choice": "auto",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": f"{tool.server_id}::{tool.name}",
                        "description": tool.description or "",
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                    },
                }
                for tool in tools
            ],
        }

        async with httpx.AsyncClient(base_url=self.settings.openai_base_url, timeout=30.0) as client:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        message = data["choices"][0]["message"]
        if message.get("tool_calls"):
            call = message["tool_calls"][0]
            server_id, tool_name = call["function"]["name"].split("::", maxsplit=1)
            arguments = json.loads(call["function"]["arguments"] or "{}")
            usage = data.get("usage", {})
            return PlannerDecision(
                assistant_message=message.get("content"),
                tool_call=ToolCall(server_id=server_id, tool_name=tool_name, arguments=arguments),
                usage_tokens=usage.get("total_tokens", 0),
            )

        usage = data.get("usage", {})
        return PlannerDecision(
            assistant_message=message.get("content") or "No response returned.",
            usage_tokens=usage.get("total_tokens", 0),
        )

    async def summarize_tool_result(
        self,
        user_message: str,
        tool_call: ToolCall,
        tool_result: dict[str, Any],
    ) -> PlannerDecision:
        payload = {
            "model": self.settings.openai_model,
            "messages": [
                {
                    "role": "system",
                    "content": "Summarize the tool result clearly for the user.",
                },
                {"role": "user", "content": user_message},
                {
                    "role": "tool",
                    "content": json.dumps(tool_result),
                    "tool_call_id": f"{tool_call.server_id}::{tool_call.tool_name}",
                },
            ],
        }
        async with httpx.AsyncClient(base_url=self.settings.openai_base_url, timeout=30.0) as client:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        usage = data.get("usage", {})
        return PlannerDecision(
            assistant_message=data["choices"][0]["message"].get("content") or "Tool call finished.",
            usage_tokens=usage.get("total_tokens", 0),
        )


def get_planner(settings: Settings) -> BasePlanner:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return OpenAICompatPlanner(settings)
    return MockPlanner()
