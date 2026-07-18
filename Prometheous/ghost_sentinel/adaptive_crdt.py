"""
Adaptive CRDT wrapper — logical CRDT merge + MCP-protected wire transport.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from ghost_sentinel.adaptive_policy import AdaptivePolicy
from ghost_sentinel.mcp_codec import MCPCodec, MCPConfig
from ghost_sentinel.serialization import deserialize_delta, serialize_delta


@runtime_checkable
class CRDTReplica(Protocol):
    """Minimal interface any CRDT backend must expose."""

    def export_delta(self) -> Dict[str, Any]: ...
    def merge(self, other_data: Dict[str, Any]) -> None: ...


class KnowledgeBaseAdapter:
    """Adapter for knowledge.crdt_knowledge.CRDTKnowledgeBase."""

    def __init__(self, kb: Any):
        self._kb = kb

    def export_delta(self) -> Dict[str, Any]:
        import json
        return json.loads(self._kb.export())

    def merge(self, other_data: Dict[str, Any]) -> None:
        self._kb.merge(other_data)


class AdaptiveCRDT:
    """
    Wraps a CRDT replica and applies MCP + adaptive policy.

    Logical CRDT never sees encoding — convergence guarantees are preserved.
    """

    def __init__(
        self,
        crdt_replica: CRDTReplica,
        mcp: MCPCodec,
        policy: Optional[AdaptivePolicy] = None,
        node_id: str = "local",
    ):
        self.crdt = crdt_replica
        self.mcp = mcp
        self.policy = policy or AdaptivePolicy(node_id=node_id)
        self.metrics: Dict[str, Any] = {
            "decode_errors": 0,
            "merges_ok": 0,
            "merges_failed": 0,
        }

    def local_op(self, op: Dict[str, Any]) -> bytes:
        """
        Apply a local operation, export delta, optionally MCP-protect.

        ``op`` is merged into the exported delta under ``_local_ops`` for v1.
        """
        delta = self.crdt.export_delta()
        ops = delta.setdefault("_local_ops", [])
        if isinstance(ops, list):
            ops.append(op)
        raw = serialize_delta(delta)
        self.policy.apply_to_mcp_config(self.mcp.config)
        if self.policy.state.security_level > 0:
            return self.mcp.protect(raw)
        return raw

    def export_wire(self) -> bytes:
        """Export current replica state as MCP-protected wire bytes."""
        raw = serialize_delta(self.crdt.export_delta())
        self.policy.apply_to_mcp_config(self.mcp.config)
        if self.policy.state.security_level > 0:
            return self.mcp.protect(raw)
        return raw

    def receive(self, wire: bytes) -> bool:
        """Decode MCP wire payload and merge into local CRDT replica."""
        t0 = time.perf_counter()
        self.policy.apply_to_mcp_config(self.mcp.config)
        raw = self.mcp.recover(wire)
        if raw is None:
            self.metrics["decode_errors"] += 1
            self.metrics["merges_failed"] += 1
            self.policy.record_decode_error()
            return False

        delta = deserialize_delta(raw)
        self.crdt.merge(delta)
        self.metrics["merges_ok"] += 1
        self.policy.record_merge((time.perf_counter() - t0) * 1000)
        return True

    @classmethod
    def from_knowledge_base(
        cls,
        kb: Any,
        seed: bytes,
        *,
        node_id: str = "local",
        config: Optional[MCPConfig] = None,
    ) -> "AdaptiveCRDT":
        mcp = MCPCodec(seed, config or MCPConfig())
        return cls(KnowledgeBaseAdapter(kb), mcp, AdaptivePolicy(node_id=node_id), node_id)