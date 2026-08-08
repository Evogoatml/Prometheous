"""
Intelligent MCP Tool Assembly — plug-and-play workflows with gated self-coding.

Phase 2 layer built on top of the Manchester Cryptographic Protocol codec.
Self-coding starts as template instantiation only (no free-form LLM codegen).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ghost_sentinel.adaptive_crdt import AdaptiveCRDT
from ghost_sentinel.adaptive_policy import AdaptivePolicy
from ghost_sentinel.mcp_codec import MCPCodec, MCPConfig
from ghost_sentinel.sandbox import dry_run
from ghost_sentinel.tool_registry import ToolRegistryCRDT, ToolSpec


# Safe template catalog — expand deliberately, never exec arbitrary strings.
TOOL_TEMPLATES: Dict[str, str] = {
    "http_probe": (
        "def run(url: str) -> dict:\n"
        "    import urllib.request\n"
        "    req = urllib.request.Request(url, headers={'User-Agent': 'GhostSentinel/1.0'})\n"
        "    with urllib.request.urlopen(req, timeout=15) as resp:\n"
        "        body = resp.read(4096)\n"
        "    return {'status': resp.status, 'bytes': len(body)}\n"
    ),
    "hash_file": (
        "def run(data: bytes) -> dict:\n"
        "    import hashlib\n"
        "    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}\n"
    ),
    "ping_check": (
        "def run(host: str = '127.0.0.1') -> dict:\n"
        "    return {'host': host, 'reachable': True, 'note': 'stub ping'}\n"
    ),
    "crdt_search": (
        "def run(query: str, items: list) -> dict:\n"
        "    q = query.lower()\n"
        "    hits = [i for i in items if q in str(i).lower()]\n"
        "    return {'query': query, 'hits': hits[:20], 'count': len(hits)}\n"
    ),
    "json_parse": (
        "def run(text: str) -> dict:\n"
        "    import json\n"
        "    obj = json.loads(text)\n"
        "    return {'type': type(obj).__name__, 'keys': list(obj.keys()) if isinstance(obj, dict) else []}\n"
    ),
}

TEMPLATE_DRY_RUN: Dict[str, Dict[str, Any]] = {
    "http_probe": {"invoke": False},
    "hash_file": {"invoke": True, "test_args": {"data": b"ghost-sentinel-test"}},
    "ping_check": {"invoke": True, "test_args": {"host": "127.0.0.1"}},
    "crdt_search": {"invoke": True, "test_args": {"query": "sql", "items": ["SQL Injection", "XSS"]}},
    "json_parse": {"invoke": True, "test_args": {"text": '{"ok": true}' }},
}


@dataclass
class WorkflowNode:
    id: str
    tool_name: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowGraph:
    name: str
    version: str = "1.0.0"
    nodes: List[WorkflowNode] = field(default_factory=list)
    edges: List[Dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowGraph":
        nodes = [
            WorkflowNode(id=n["id"], tool_name=n["tool"], params=n.get("params", {}))
            for n in data.get("nodes", [])
        ]
        return cls(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            nodes=nodes,
            edges=data.get("edges", []),
        )


class ToolAssemblyEngine:
    """
    Composes plug-and-play workflows from CRDT-backed tool registry.

    All artifacts distributed via AdaptiveCRDT + MCP protection.
    """

    ALLOWED_CAPABILITIES = frozenset({
        "http.get", "fs.read", "hash", "ping", "crdt.read", "json.parse",
    })

    def __init__(
        self,
        registry: ToolRegistryCRDT,
        mcp: MCPCodec,
        policy: Optional[AdaptivePolicy] = None,
        node_id: str = "local",
    ):
        self.registry = registry
        self.policy = policy or AdaptivePolicy(node_id=node_id)
        self.transport = AdaptiveCRDT(
            _RegistryAdapter(registry),
            mcp,
            self.policy,
            node_id,
        )

    def propose_tool_from_template(
        self,
        name: str,
        template_id: str,
        *,
        capabilities: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self.policy.state.pause_tool_registration:
            return {"error": "tool registration paused (threat posture)"}
        if template_id not in TOOL_TEMPLATES:
            return {"error": f"unknown template: {template_id}"}

        caps = capabilities or _infer_capabilities(template_id)
        blocked = [c for c in caps if c not in self.ALLOWED_CAPABILITIES]
        if blocked:
            return {"error": f"capabilities not allowed: {blocked}"}

        code = TOOL_TEMPLATES[template_id]
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        spec = ToolSpec(
            name=name,
            version="1.0.0",
            description=f"Template-generated: {template_id}",
            capabilities=caps,
            template_id=template_id,
            parameters=parameters or {},
            code_hash=code_hash,
        )
        tool_id = self.registry.propose(spec)
        gates = self._run_gates(code, caps, template_id=template_id)
        if not gates["passed"]:
            self.registry.revoke(tool_id)
            return {"error": "gates failed", "gates": gates}

        self.registry.vet(tool_id, gates_passed=gates["checks"])
        self.registry.register(tool_id)
        return {
            "tool_id": tool_id,
            "name": name,
            "status": "registered",
            "code_hash": code_hash,
            "capabilities": caps,
        }

    def compose_workflow(self, graph: WorkflowGraph) -> Dict[str, Any]:
        registered = {t.name for t in self.registry.list_registered()}
        missing = [n.tool_name for n in graph.nodes if n.tool_name not in registered]
        if missing:
            return {"error": "missing registered tools", "missing": missing}
        return {
            "workflow": graph.name,
            "version": graph.version,
            "nodes": [n.id for n in graph.nodes],
            "edges": graph.edges,
            "status": "composed",
        }

    def publish_registry_delta(self) -> bytes:
        return self.transport.export_wire()

    def receive_registry_delta(self, wire: bytes) -> bool:
        return self.transport.receive(wire)

    def _run_gates(
        self,
        code: str,
        capabilities: List[str],
        template_id: str = "",
    ) -> Dict[str, Any]:
        checks: List[str] = []
        passed = True

        if re.search(r"\bos\.system\b|\bsubprocess\b|\beval\b|\bexec\b", code):
            passed = False
            checks.append("static_analysis:BLOCKED_SYSCALLS")
        else:
            checks.append("static_analysis:ok")

        for cap in capabilities:
            if cap in self.ALLOWED_CAPABILITIES:
                checks.append(f"capability:{cap}:ok")
            else:
                passed = False
                checks.append(f"capability:{cap}:DENIED")

        dry_cfg = TEMPLATE_DRY_RUN.get(template_id, {"invoke": False})
        sandbox = dry_run(
            code,
            invoke=bool(dry_cfg.get("invoke")),
            test_args=dry_cfg.get("test_args"),
        )
        checks.extend(sandbox.get("checks", []))
        if not sandbox.get("passed", False):
            passed = False
            self.policy.telemetry.sandbox_anomalies += 1
            self.policy._adapt()

        return {"passed": passed, "checks": checks}


class _RegistryAdapter:
    def __init__(self, registry: ToolRegistryCRDT):
        self._registry = registry

    def export_delta(self) -> Dict[str, Any]:
        return self._registry.export()

    def merge(self, other_data: Dict[str, Any]) -> None:
        self._registry.merge(other_data)


def _infer_capabilities(template_id: str) -> List[str]:
    mapping = {
        "http_probe": ["http.get"],
        "hash_file": ["hash"],
        "ping_check": ["ping"],
        "crdt_search": ["crdt.read"],
        "json_parse": ["json.parse"],
    }
    return mapping.get(template_id, ["ping"])