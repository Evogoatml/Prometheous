"""
MCP client — thin adapter over the in-process MCP tool server (mcp.server).

The real client is `mcp.server.MCPClient.call`. This module keeps the
async list_tools / call_tool surface for callers that import it directly,
and mirrors `MCPClient.call` for parity with the orchestrator path.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


class MCPClient:
    """In-process MCP client backed by mcp.server.ToolRegistry."""

    def __init__(self):
        self._registry = None
        self._init()

    def _init(self):
        try:
            from mcp.server import ToolRegistry
            self._registry = ToolRegistry
        except Exception:
            self._registry = None

    @staticmethod
    def call(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from mcp.server import MCPClient as ServerClient
        return ServerClient.call(name, arguments)

    async def list_tools(self) -> List[str]:
        """Return the names of all tools registered with the in-process server."""
        if self._registry is None:
            return []
        return sorted(self._registry.tools.keys())

    async def call_tool(self, name: str, args: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Call a tool and return a JSON string (None if the server is unavailable)."""
        if self._registry is None:
            return None
        result = self._registry.execute(name, args or {})
        if isinstance(result, (dict, list)):
            return json.dumps(result)
        return str(result) if result is not None else None

    async def close(self):
        self._registry = None
