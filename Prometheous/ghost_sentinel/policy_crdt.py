"""
Policy CRDT — swarm-convergent security posture via LWW registers per field.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dataclasses import dataclass as _dataclass


@_dataclass
class PolicyState:
    security_level: int = 1
    roll_rate: int = 1
    max_roll_window: int = 2
    pause_tool_registration: bool = False
    node_id: str = "local"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "security_level": self.security_level,
            "roll_rate": self.roll_rate,
            "max_roll_window": self.max_roll_window,
            "pause_tool_registration": self.pause_tool_registration,
            "node_id": self.node_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyState":
        return cls(
            security_level=int(data.get("security_level", 1)),
            roll_rate=int(data.get("roll_rate", 1)),
            max_roll_window=int(data.get("max_roll_window", 2)),
            pause_tool_registration=bool(data.get("pause_tool_registration", False)),
            node_id=str(data.get("node_id", "local")),
            timestamp=float(data.get("timestamp", time.time())),
        )


@dataclass
class LWWField:
    value: Any
    node_id: str
    timestamp: float = field(default_factory=time.time)

    def merge(self, other: "LWWField") -> "LWWField":
        if other.timestamp > self.timestamp:
            return other
        return self


class PolicyCRDT:
    """
    Replicated policy document. Each field is LWW — swarm converges on
    the highest-timestamp write per key.
    """

    FIELDS = (
        "security_level",
        "roll_rate",
        "max_roll_window",
        "pause_tool_registration",
    )

    def __init__(self, node_id: str = "local"):
        self.node_id = node_id
        self._fields: Dict[str, LWWField] = {}
        self._init_defaults()

    def _init_defaults(self) -> None:
        defaults = PolicyState(node_id=self.node_id)
        for name in self.FIELDS:
            self._set_local(name, getattr(defaults, name))

    def _set_local(self, name: str, value: Any) -> None:
        self._fields[name] = LWWField(value=value, node_id=self.node_id, timestamp=time.time())

    def set_field(self, name: str, value: Any) -> None:
        if name not in self.FIELDS:
            raise KeyError(f"unknown policy field: {name}")
        self._set_local(name, value)

    def get_state(self) -> PolicyState:
        return PolicyState(
            security_level=int(self._fields["security_level"].value),
            roll_rate=int(self._fields["roll_rate"].value),
            max_roll_window=int(self._fields["max_roll_window"].value),
            pause_tool_registration=bool(self._fields["pause_tool_registration"].value),
            node_id=self.node_id,
            timestamp=max(f.timestamp for f in self._fields.values()),
        )

    def apply_state(self, state: PolicyState) -> None:
        for name in self.FIELDS:
            self._set_local(name, getattr(state, name))

    def merge(self, remote: Dict[str, Any]) -> List[str]:
        """Merge remote policy CRDT export. Returns list of changed fields."""
        changed: List[str] = []
        for name, data in remote.get("fields", {}).items():
            if name not in self.FIELDS:
                continue
            incoming = LWWField(
                value=data["value"],
                node_id=data.get("node_id", "remote"),
                timestamp=float(data.get("timestamp", 0)),
            )
            current = self._fields.get(name, LWWField(value=None, node_id=self.node_id))
            merged = current.merge(incoming)
            if merged.timestamp > current.timestamp:
                self._fields[name] = merged
                changed.append(name)
        return changed

    def export(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "fields": {
                name: {
                    "value": f.value,
                    "node_id": f.node_id,
                    "timestamp": f.timestamp,
                }
                for name, f in self._fields.items()
            },
        }

    def escalate(self, *, reason: str = "threat") -> PolicyState:
        """Local escalation helper — bumps security and optionally pauses tools."""
        level = int(self._fields["security_level"].value)
        self.set_field("security_level", min(2, level + 1))
        window = int(self._fields["max_roll_window"].value)
        self.set_field("max_roll_window", min(4, window + 1))
        if reason in ("honeypot", "sandbox"):
            self.set_field("pause_tool_registration", True)
        return self.get_state()