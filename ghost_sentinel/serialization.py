"""Delta serialization for CRDT payloads before MCP protection."""
from __future__ import annotations

import json
from typing import Any, Dict


def serialize_delta(delta: Dict[str, Any]) -> bytes:
    """JSON serialization (v1 default — msgpack can be added later)."""
    return json.dumps(delta, separators=(",", ":"), sort_keys=True).encode("utf-8")


def deserialize_delta(raw: bytes) -> Dict[str, Any]:
    return json.loads(raw.decode("utf-8"))