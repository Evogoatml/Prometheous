"""
CRDT-backed tool registry for Ghost Sentinel intelligent assembly.

Tools are signed specs stored in an OR-Set style structure with tombstones.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set

from ghost_sentinel.crypto_seed import mac_payload


@dataclass
class ToolSpec:
    name: str
    version: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    template_id: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    code_hash: str = ""
    status: str = "proposed"  # proposed | vetted | registered | revoked
    node_id: str = "local"
    timestamp: float = field(default_factory=time.time)

    def content_bytes(self) -> bytes:
        payload = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "capabilities": sorted(self.capabilities),
            "template_id": self.template_id,
            "parameters": self.parameters,
            "code_hash": self.code_hash,
            "status": self.status,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def sign(self, seed: bytes) -> str:
        return mac_payload(self.content_bytes(), seed, length=32).hex()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ToolRegistryCRDT:
    """OR-Set style registry with tombstones for revocation."""

    def __init__(self, node_id: str = "local", seed: Optional[bytes] = None):
        self.node_id = node_id
        self.seed = seed or b"ghost-sentinel-tool-registry-v1\x00" * 2
        self.tools: Dict[str, ToolSpec] = {}
        self.tombstones: Set[str] = set()
        self.signatures: Dict[str, str] = {}

    def _tool_id(self, name: str, version: str) -> str:
        return hashlib.sha256(f"{name}:{version}".encode()).hexdigest()[:16]

    def propose(self, spec: ToolSpec) -> str:
        spec.node_id = self.node_id
        spec.timestamp = time.time()
        spec.status = "proposed"
        tool_id = self._tool_id(spec.name, spec.version)
        self.tools[tool_id] = spec
        self.signatures[tool_id] = spec.sign(self.seed)
        return tool_id

    def vet(self, tool_id: str, *, gates_passed: Optional[List[str]] = None) -> bool:
        if tool_id not in self.tools or tool_id in self.tombstones:
            return False
        spec = self.tools[tool_id]
        if self.signatures.get(tool_id) != spec.sign(self.seed):
            return False
        spec.status = "vetted"
        spec.parameters["_gates"] = gates_passed or ["static_analysis", "capability_check"]
        self.signatures[tool_id] = spec.sign(self.seed)
        return True

    def register(self, tool_id: str) -> bool:
        if tool_id not in self.tools or tool_id in self.tombstones:
            return False
        spec = self.tools[tool_id]
        if spec.status not in ("vetted", "registered"):
            return False
        if self.signatures.get(tool_id) != spec.sign(self.seed):
            return False
        spec.status = "registered"
        self.tombstones.discard(tool_id)
        self.signatures[tool_id] = spec.sign(self.seed)
        return True

    def revoke(self, tool_id: str) -> None:
        self.tombstones.add(tool_id)
        if tool_id in self.tools:
            self.tools[tool_id].status = "revoked"

    def list_registered(self) -> List[ToolSpec]:
        return [
            s for tid, s in self.tools.items()
            if tid not in self.tombstones and s.status == "registered"
        ]

    def merge(self, remote: Dict[str, Any]) -> None:
        for tid, data in remote.get("tools", {}).items():
            if tid in remote.get("tombstones", []):
                self.tombstones.add(tid)
                continue
            spec = ToolSpec(**data)
            sig = remote.get("signatures", {}).get(tid, "")
            if sig != spec.sign(self.seed):
                continue
            existing = self.tools.get(tid)
            if existing is None or spec.timestamp > existing.timestamp:
                self.tools[tid] = spec
                self.signatures[tid] = sig
        self.tombstones.update(remote.get("tombstones", []))

    def export(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "tools": {tid: s.to_dict() for tid, s in self.tools.items()},
            "tombstones": list(self.tombstones),
            "signatures": dict(self.signatures),
        }