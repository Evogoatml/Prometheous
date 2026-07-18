"""
Ghost Sentinel swarm coordinator — ties CRDT, policy, registry, and file relay.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ghost_sentinel.adaptive_crdt import AdaptiveCRDT, KnowledgeBaseAdapter
from ghost_sentinel.adaptive_policy import AdaptivePolicy
from ghost_sentinel.mcp_codec import MCPCodec, MCPConfig
from ghost_sentinel.serialization import serialize_delta
from ghost_sentinel.tool_assembly import ToolAssemblyEngine, _RegistryAdapter
from ghost_sentinel.tool_registry import ToolRegistryCRDT
from ghost_sentinel.relay import build_relay_transport
from ghost_sentinel.transport import FileRelayTransport


class GhostSentinelSwarm:
    """Single-node swarm member with P2P file relay + policy CRDT sync."""

    def __init__(
        self,
        node_id: str,
        seed: bytes,
        *,
        kb: Any = None,
        relay_root: Optional[Path] = None,
        relay_mode: Optional[str] = None,
        ws_url: Optional[str] = None,
    ):
        from knowledge.crdt_knowledge import CRDTKnowledgeBase

        self.node_id = node_id
        self.seed = seed
        self.policy = AdaptivePolicy(node_id=node_id)
        self.mcp = MCPCodec(seed, MCPConfig())

        self.kb = kb or CRDTKnowledgeBase(node_id=f"{node_id}-sentinel")
        self.crdt = AdaptiveCRDT(
            KnowledgeBaseAdapter(self.kb),
            self.mcp,
            self.policy,
            node_id,
        )

        self.registry = ToolRegistryCRDT(node_id=node_id, seed=seed)
        self.assembly = ToolAssemblyEngine(self.registry, self.mcp, self.policy, node_id)

        self.policy_transport = AdaptiveCRDT(
            _PolicyAdapter(self.policy),
            self.mcp,
            self.policy,
            node_id,
        )

        self.relay = build_relay_transport(
            node_id,
            relay_root=relay_root,
            mode=relay_mode,
            ws_url=ws_url,
        )

    def _publish_wire(self, wire: bytes, *, kind: str) -> Path:
        level = self.policy.crdt.get_state().security_level
        return self.relay.publish(wire, kind=kind, security_level=level)

    def publish_crdt(self) -> Path:
        self.policy.apply_to_mcp_config(self.mcp.config)
        wire = self.crdt.export_wire()
        return self._publish_wire(wire, kind="crdt_delta")

    def publish_policy(self) -> Path:
        self.policy.apply_to_mcp_config(self.mcp.config)
        raw = serialize_delta({"policy": self.policy.export_crdt()})
        wire = self.mcp.protect(raw)
        return self._publish_wire(wire, kind="policy")

    def publish_registry(self) -> Path:
        self.policy.apply_to_mcp_config(self.mcp.config)
        wire = self.assembly.publish_registry_delta()
        return self._publish_wire(wire, kind="registry")

    def poll_relay(self) -> Dict[str, Any]:
        results: Dict[str, Any] = {"crdt": 0, "policy": 0, "registry": 0, "failed": 0}

        def handler(wire: bytes, env) -> bool:
            saved_level = self.mcp.config.security_level
            self.mcp.config.security_level = env.security_level
            try:
                if env.kind == "policy":
                    raw = self.mcp.recover(wire)
                    if raw is None:
                        results["failed"] += 1
                        return False
                    data = json.loads(raw.decode("utf-8"))
                    changed = self.policy.merge_crdt(data.get("policy", {}))
                    results["policy"] += len(changed)
                    return True
                if env.kind == "registry":
                    ok = self.assembly.receive_registry_delta(wire)
                    if ok:
                        results["registry"] += 1
                    else:
                        results["failed"] += 1
                    return ok
                ok = self.crdt.receive(wire)
                if ok:
                    results["crdt"] += 1
                else:
                    results["failed"] += 1
                return ok
            finally:
                self.mcp.config.security_level = max(saved_level, env.security_level)
                self.policy.apply_to_mcp_config(self.mcp.config)

        stats = self.relay.poll(handler)
        return {"relay": stats, "merged": results}


class _PolicyAdapter:
    def __init__(self, policy: AdaptivePolicy):
        self._policy = policy

    def export_delta(self) -> Dict[str, Any]:
        return {"policy": self._policy.export_crdt()}

    def merge(self, other_data: Dict[str, Any]) -> None:
        self._policy.merge_crdt(other_data.get("policy", {}))