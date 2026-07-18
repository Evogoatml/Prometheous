"""
Adaptive policy engine for Ghost Sentinel.

Observes local metrics + security signals and tunes MCP security posture.
Policy state can be replicated as a lightweight CRDT (LWW per field).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ghost_sentinel.policy_crdt import PolicyCRDT, PolicyState


@dataclass
class TelemetrySnapshot:
    decode_errors: int = 0
    honeypot_hits: int = 0
    last_merge_ms: float = 0.0
    sandbox_anomalies: int = 0


class AdaptivePolicy:
    """Heuristic policy engine — escalates protection under threat signals."""

    MAX_SECURITY = 2

    def __init__(self, node_id: str = "local", initial: Optional[PolicyState] = None):
        self.node_id = node_id
        self.crdt = PolicyCRDT(node_id=node_id)
        if initial:
            self.crdt.apply_state(initial)
        self.state = self.crdt.get_state()
        self.telemetry = TelemetrySnapshot()

    def record_decode_error(self) -> None:
        self.telemetry.decode_errors += 1
        self._adapt()

    def record_honeypot_hit(self) -> None:
        self.telemetry.honeypot_hits += 1
        self._adapt()

    def record_merge(self, duration_ms: float) -> None:
        self.telemetry.last_merge_ms = duration_ms
        if duration_ms > 500:
            self.state.roll_rate = max(1, self.state.roll_rate - 1)

    def merge_remote(self, remote: PolicyState) -> None:
        """LWW merge for swarm-wide policy convergence."""
        if remote.timestamp > self.state.timestamp:
            self.crdt.apply_state(remote)
            self.state = self.crdt.get_state()

    def merge_crdt(self, remote_export: Dict[str, Any]) -> List[str]:
        """Merge a PolicyCRDT export from a peer."""
        changed = self.crdt.merge(remote_export)
        self.state = self.crdt.get_state()
        return changed

    def export_crdt(self) -> Dict[str, Any]:
        return self.crdt.export()

    def set_field(self, name: str, value: Any) -> None:
        """Update a policy field locally and refresh cached state."""
        self.crdt.set_field(name, value)
        self.state = self.crdt.get_state()

    def _adapt(self) -> None:
        if self.telemetry.decode_errors > 3:
            current = self.crdt.get_state()
            self.crdt.set_field(
                "security_level",
                min(self.MAX_SECURITY, current.security_level + 1),
            )
            self.crdt.set_field(
                "max_roll_window",
                min(4, current.max_roll_window + 1),
            )
            self.telemetry.decode_errors = 0

        if self.telemetry.honeypot_hits > 0:
            self.crdt.escalate(reason="honeypot")
            self.telemetry.honeypot_hits = 0

        if self.telemetry.sandbox_anomalies > 2:
            self.crdt.set_field("pause_tool_registration", True)

        self.state = self.crdt.get_state()

    def apply_to_mcp_config(self, config: Any) -> None:
        """Mutate an MCPConfig in place from current policy."""
        self.state = self.crdt.get_state()
        config.security_level = self.state.security_level
        config.max_roll_window = self.state.max_roll_window