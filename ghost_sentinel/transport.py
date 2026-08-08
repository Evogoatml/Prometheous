"""
P2P transport for Ghost Sentinel — file-relay v1 (dumb pipe, MCP-protected payloads).

Agents drop MCP wire blobs into a shared directory; peers poll and ingest.
No central coordinator required beyond filesystem visibility.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class RelayEnvelope:
    sender: str
    channel: str
    seq: int
    wire_b64: str
    timestamp: float = field(default_factory=time.time)
    kind: str = "crdt_delta"  # crdt_delta | policy | registry
    security_level: int = 1

    def to_json(self) -> str:
        return json.dumps({
            "sender": self.sender,
            "channel": self.channel,
            "seq": self.seq,
            "wire_b64": self.wire_b64,
            "timestamp": self.timestamp,
            "kind": self.kind,
            "security_level": self.security_level,
        }, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "RelayEnvelope":
        data = json.loads(raw)
        return cls(
            sender=data["sender"],
            channel=data["channel"],
            seq=int(data["seq"]),
            wire_b64=data["wire_b64"],
            timestamp=float(data.get("timestamp", time.time())),
            kind=data.get("kind", "crdt_delta"),
            security_level=int(data.get("security_level", 1)),
        )


class FileRelayTransport:
    """
    File-based relay transport.

    Layout::
        {root}/{channel}/{sender}_{seq:012d}.json
    """

    def __init__(
        self,
        root: Path,
        node_id: str,
        channel: str = "ghost-sentinel",
    ):
        self.root = Path(root)
        self.node_id = node_id
        self.channel = channel
        self._seq = 0
        self._seen: set[str] = set()
        self._inbox = self.root / channel
        self._inbox.mkdir(parents=True, exist_ok=True)
        self._load_seq_counter()

    def _load_seq_counter(self) -> None:
        for path in sorted(self._inbox.glob(f"{self.node_id}_*.json")):
            try:
                seq = int(path.stem.split("_", 1)[1])
                self._seq = max(self._seq, seq + 1)
            except (IndexError, ValueError):
                continue

    def publish(self, wire: bytes, *, kind: str = "crdt_delta", security_level: int = 1) -> Path:
        import base64

        env = RelayEnvelope(
            sender=self.node_id,
            channel=self.channel,
            seq=self._seq,
            wire_b64=base64.b64encode(wire).decode("ascii"),
            kind=kind,
            security_level=security_level,
        )
        path = self._inbox / f"{self.node_id}_{self._seq:012d}.json"
        path.write_text(env.to_json(), encoding="utf-8")
        self._seq += 1
        return path

    def poll(
        self,
        handler: Callable[[bytes, RelayEnvelope], bool],
        *,
        since: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Ingest new envelopes from other senders.

        ``handler(wire, envelope)`` should return True on successful merge.
        """
        stats = {"scanned": 0, "ingested": 0, "failed": 0, "skipped": 0}
        since = since or 0.0

        for path in sorted(self._inbox.glob("*.json")):
            stats["scanned"] += 1
            key = str(path.resolve())
            if key in self._seen:
                stats["skipped"] += 1
                continue

            try:
                env = RelayEnvelope.from_json(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError):
                stats["failed"] += 1
                self._seen.add(key)
                continue

            if env.sender == self.node_id:
                self._seen.add(key)
                stats["skipped"] += 1
                continue
            if env.timestamp < since:
                self._seen.add(key)
                stats["skipped"] += 1
                continue

            import base64
            try:
                wire = base64.b64decode(env.wire_b64.encode("ascii"))
            except Exception:
                stats["failed"] += 1
                self._seen.add(key)
                continue

            ok = handler(wire, env)
            self._seen.add(key)
            if ok:
                stats["ingested"] += 1
            else:
                stats["failed"] += 1

        return stats

    @classmethod
    def default_root(cls) -> Path:
        env = os.getenv("GHOST_SENTINEL_RELAY_ROOT", "")
        if env:
            return Path(env)
        return Path.home() / ".prometheous" / "ghost_sentinel" / "relay"