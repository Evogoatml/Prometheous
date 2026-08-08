"""
Relay transport abstraction — file, WebSocket, or composite (both).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol, runtime_checkable

from ghost_sentinel.transport import FileRelayTransport, RelayEnvelope


@runtime_checkable
class RelayTransport(Protocol):
    root: Path

    def publish(self, wire: bytes, *, kind: str = "crdt_delta", security_level: int = 1) -> Any: ...
    def poll(
        self,
        handler: Callable[[bytes, RelayEnvelope], bool],
        *,
        since: Optional[float] = None,
    ) -> Dict[str, Any]: ...


class CompositeRelayTransport:
    """Publish to all backends; poll merges stats from each."""

    def __init__(self, backends: list[RelayTransport]):
        if not backends:
            raise ValueError("at least one relay backend required")
        self.backends = backends
        self.root = backends[0].root

    def publish(self, wire: bytes, *, kind: str = "crdt_delta", security_level: int = 1) -> Any:
        results = []
        for backend in self.backends:
            results.append(backend.publish(wire, kind=kind, security_level=security_level))
        return results[0]

    def poll(
        self,
        handler: Callable[[bytes, RelayEnvelope], bool],
        *,
        since: Optional[float] = None,
    ) -> Dict[str, Any]:
        totals = {"scanned": 0, "ingested": 0, "failed": 0, "skipped": 0}
        for backend in self.backends:
            stats = backend.poll(handler, since=since)
            for key in totals:
                totals[key] += int(stats.get(key, 0))
        return totals


def build_relay_transport(
    node_id: str,
    *,
    relay_root: Optional[Path] = None,
    mode: Optional[str] = None,
    ws_url: Optional[str] = None,
) -> RelayTransport:
    """
    Factory for relay backends.

    ``GHOST_SENTINEL_RELAY_MODE``: ``file`` | ``ws`` | ``both`` (default ``file``)
    ``GHOST_SENTINEL_WS_URL``: e.g. ``ws://127.0.0.1:8765``
    """
    mode = (mode or os.getenv("GHOST_SENTINEL_RELAY_MODE", "file")).lower()
    ws_url = ws_url or os.getenv("GHOST_SENTINEL_WS_URL", "ws://127.0.0.1:8765")
    root = relay_root or FileRelayTransport.default_root()

    backends: list[RelayTransport] = []

    if mode in ("file", "both"):
        backends.append(FileRelayTransport(root, node_id))

    if mode in ("ws", "both"):
        from ghost_sentinel.ws_relay import WebSocketRelayTransport

        backends.append(WebSocketRelayTransport(ws_url, node_id, fallback_root=root))

    if not backends:
        backends.append(FileRelayTransport(root, node_id))

    if len(backends) == 1:
        return backends[0]
    return CompositeRelayTransport(backends)