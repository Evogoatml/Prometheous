"""
MCP tools agent — executes function calls through the orchestrator.
"""
from __future__ import annotations

from typing import Any, Dict

from llm.tool_router import ToolCall, execute_tool, format_tool_reply


class McpToolsAgent:
    name = "mcp_tools"
    role = "McpTools"
    specialty = "MCP function calling (fs, http, shell, healing)"
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        tool_name = payload.get("tool_name") or payload.get("tool")
        tool_args = payload.get("tool_args") or payload.get("arguments") or {}

        if not tool_name:
            return {
                "status": "failed",
                "agent": self.name,
                "error": "missing tool_name",
            }

        if not tool_args and payload.get("user_msg"):
            from llm.tool_router import classify_tool
            inferred = classify_tool(str(payload["user_msg"]))
            if inferred and inferred.name == tool_name:
                tool_args = inferred.arguments

        call = ToolCall(
            name=tool_name,
            arguments=tool_args,
            confidence=float(payload.get("confidence", 0)),
            source=payload.get("source", "orchestrator"),
        )
        result = execute_tool(call)
        formatted = format_tool_reply(call, result)
        ok = result.get("status") != "error" and not result.get("error")

        return {
            "status": "ok" if ok else "failed",
            "agent": self.name,
            "tool": tool_name,
            "arguments": tool_args,
            "result": result,
            "formatted": formatted,
        }