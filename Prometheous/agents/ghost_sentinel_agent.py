"""
Ghost Sentinel agent — CRDT+MCP, tool assembly, P2P relay, policy CRDT sync.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from ghost_sentinel import GhostSentinelSwarm, derive_swarm_seed
from ghost_sentinel.tool_assembly import WorkflowGraph


class GhostSentinelAgent:
    name = "ghost_sentinel"
    role = "Ghost Sentinel"
    specialty = "Adaptive CRDT + Rolling Manchester MCP + gated tool assembly"
    tasks_completed = 0

    def __init__(self) -> None:
        swarm_id = os.getenv("GHOST_SENTINEL_SWARM_ID", "prometheous")
        relay_root = os.getenv("GHOST_SENTINEL_RELAY_ROOT", "")
        self.relay_mode = os.getenv("GHOST_SENTINEL_RELAY_MODE", "file")
        self.ws_url = os.getenv("GHOST_SENTINEL_WS_URL", "ws://127.0.0.1:8765")
        self.seed = derive_swarm_seed(swarm_id=swarm_id)
        self.swarm = GhostSentinelSwarm(
            swarm_id,
            self.seed,
            relay_root=Path(relay_root) if relay_root else None,
            relay_mode=self.relay_mode,
            ws_url=self.ws_url,
        )

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        action = payload.get("action") or payload.get("mode") or "status"
        msg = (payload.get("user_msg") or "").lower()

        if action == "sync" or "sync crdt" in msg:
            path = self.swarm.publish_crdt()
            return {"status": "ok", "action": "sync", "published": str(path)}

        if action == "poll" or "poll relay" in msg:
            result = self.swarm.poll_relay()
            return {"status": "ok", "action": "poll", "result": result}

        if action == "sync_policy" or "sync policy" in msg:
            path = self.swarm.publish_policy()
            return {"status": "ok", "action": "sync_policy", "published": str(path)}

        if action == "propose_tool" or "propose tool" in msg:
            template = payload.get("template", "http_probe")
            tool_name = payload.get("tool_name", "dynamic_probe")
            result = self.swarm.assembly.propose_tool_from_template(tool_name, template)
            if "tool_id" in result:
                self.swarm.publish_registry()
            return {"status": "ok", "result": result}

        if action == "compose" or "workflow" in msg:
            graph_data = payload.get("workflow") or {
                "name": "default-flow",
                "nodes": [{"id": "n1", "tool": payload.get("tool_name", "dynamic_probe")}],
            }
            graph = WorkflowGraph.from_dict(graph_data)
            result = self.swarm.assembly.compose_workflow(graph)
            return {"status": "ok", "result": result}

        if action == "templates":
            from ghost_sentinel.tool_assembly import TOOL_TEMPLATES
            return {"status": "ok", "templates": list(TOOL_TEMPLATES.keys())}

        if action == "help":
            from ghost_sentinel.telegram_cmds import SENTINEL_HELP
            return {"status": "ok", "action": "help", "message": SENTINEL_HELP}

        if action == "relay_status":
            return {
                "status": "ok",
                "action": "relay_status",
                "relay_mode": self.relay_mode,
                "ws_url": self.ws_url,
                "relay_root": str(self.swarm.relay.root),
            }

        return {
            "status": "ok",
            "agent": self.name,
            "crypto_backend": __import__("ghost_sentinel.crypto_seed", fromlist=["crypto_backend"]).crypto_backend(),
            "policy": self.swarm.policy.state.to_dict(),
            "policy_crdt": self.swarm.policy.export_crdt(),
            "registered_tools": [t.name for t in self.swarm.registry.list_registered()],
            "metrics": self.swarm.crdt.metrics,
            "relay_root": str(self.swarm.relay.root),
            "relay_mode": self.relay_mode,
            "ws_url": self.ws_url,
        }