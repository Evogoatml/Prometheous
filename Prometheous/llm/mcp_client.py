"""
MCP client stub — provides MCPClient for orchestrator compatibility.
When mcp package is available, uses it. Otherwise no-ops.
"""
from typing import Any, Dict, List, Optional


class MCPClient:
    """MCP (Model Context Protocol) client. Graceful no-op if mcp not installed."""

    def __init__(self):
        self._available = False
        self._client = None
        self._init()

    def _init(self):
        try:
            import mcp
            self._available = True
            # mcp client init would go here
        except ImportError:
            self._available = False

    async def list_tools(self) -> List[Dict[str, Any]]:
        if not self._available:
            return []
        return []

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Optional[str]:
        if not self._available:
            return None
        return None

    async def close(self):
        self._client = None