"""
WebSocket relay for Ghost Sentinel — dumb pipe with MCP envelope broadcast.

Run standalone server::
    python scripts/ghost_sentinel_ws_relay.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional, Set

from ghost_sentinel.transport import FileRelayTransport, RelayEnvelope

logger = logging.getLogger(__name__)

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    from websockets.sync.client import connect as ws_connect

    _HAS_WS = True
except ImportError:
    websockets = None  # type: ignore[assignment]
    WebSocketServerProtocol = object  # type: ignore[misc, assignment]
    ws_connect = None  # type: ignore[assignment]
    _HAS_WS = False


class WebSocketRelayServer:
    """In-memory envelope hub — broadcasts publishes to all connected clients."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, *, backlog: int = 256):
        self.host = host
        self.port = port
        self._backlog: Deque[str] = deque(maxlen=backlog)
        self._clients: Set[Any] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server = None

    async def _handler(self, websocket: WebSocketServerProtocol) -> None:
        self._clients.add(websocket)
        try:
            for item in list(self._backlog):
                await websocket.send(item)
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") != "publish":
                    continue
                envelope = msg.get("envelope")
                if not envelope:
                    continue
                payload = json.dumps({"type": "envelope", "envelope": envelope}, separators=(",", ":"))
                self._backlog.append(payload)
                stale = []
                for client in self._clients:
                    if client is websocket:
                        continue
                    try:
                        await client.send(payload)
                    except Exception:
                        stale.append(client)
                for client in stale:
                    self._clients.discard(client)
        finally:
            self._clients.discard(websocket)

    def start(self, *, background: bool = True) -> None:
        if not _HAS_WS:
            raise RuntimeError("websockets package required: pip install websockets")

        def _run() -> None:
            async def _main() -> None:
                async with websockets.serve(self._handler, self.host, self.port):
                    await asyncio.Future()

            asyncio.run(_main())

        if background:
            self._thread = threading.Thread(target=_run, name="gs-ws-relay", daemon=True)
            self._thread.start()
            time.sleep(0.3)
        else:
            _run()

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"


class WebSocketRelayTransport:
    """
    WebSocket client transport.

    Falls back to writing envelopes into the file relay inbox when WS is down.
    """

    def __init__(
        self,
        url: str,
        node_id: str,
        *,
        channel: str = "ghost-sentinel",
        fallback_root: Optional[Path] = None,
    ):
        if not _HAS_WS:
            raise RuntimeError("websockets package required: pip install websockets")

        self.url = url
        self.node_id = node_id
        self.channel = channel
        self._seq = 0
        self._seen: set[str] = set()
        self._inbound: queue.Queue[tuple[bytes, RelayEnvelope]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._fallback = FileRelayTransport(
            fallback_root or FileRelayTransport.default_root(),
            node_id,
            channel=channel,
        )
        self.root = self._fallback.root
        self._start_listener()

    def _envelope_key(self, env: RelayEnvelope) -> str:
        return f"{env.sender}:{env.seq}:{env.kind}"

    def _start_listener(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, name="gs-ws-client", daemon=True)
        self._thread.start()

    def _listen_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                with ws_connect(self.url, open_timeout=5) as ws:
                    backoff = 1.0
                    while self._running:
                        raw = ws.recv(timeout=30)
                        if not raw:
                            continue
                        msg = json.loads(raw)
                        if msg.get("type") != "envelope":
                            continue
                        env_data = msg.get("envelope") or {}
                        try:
                            env = RelayEnvelope(
                                sender=env_data["sender"],
                                channel=env_data.get("channel", self.channel),
                                seq=int(env_data["seq"]),
                                wire_b64=env_data["wire_b64"],
                                timestamp=float(env_data.get("timestamp", time.time())),
                                kind=env_data.get("kind", "crdt_delta"),
                                security_level=int(env_data.get("security_level", 1)),
                            )
                        except (KeyError, TypeError, ValueError):
                            continue
                        if env.sender == self.node_id:
                            continue
                        key = self._envelope_key(env)
                        if key in self._seen:
                            continue
                        import base64
                        try:
                            wire = base64.b64decode(env.wire_b64.encode("ascii"))
                        except Exception:
                            continue
                        self._inbound.put((wire, env))
            except Exception as exc:
                logger.debug("ws relay reconnect: %s", exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 15.0)

    def _ws_publish(self, env: RelayEnvelope) -> bool:
        try:
            with ws_connect(self.url, open_timeout=3) as ws:
                ws.send(json.dumps({
                    "type": "publish",
                    "envelope": json.loads(env.to_json()),
                }))
            return True
        except Exception as exc:
            logger.debug("ws publish failed, using file fallback: %s", exc)
            return False

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
        self._seq += 1
        if not self._ws_publish(env):
            return self._fallback.publish(wire, kind=kind, security_level=security_level)
        return self._fallback.root / self.channel / f"{self.node_id}_ws_{env.seq:012d}.json"

    def poll(
        self,
        handler: Callable[[bytes, RelayEnvelope], bool],
        *,
        since: Optional[float] = None,
    ) -> Dict[str, Any]:
        stats = {"scanned": 0, "ingested": 0, "failed": 0, "skipped": 0}
        since = since or 0.0

        while True:
            try:
                wire, env = self._inbound.get_nowait()
            except queue.Empty:
                break
            stats["scanned"] += 1
            key = self._envelope_key(env)
            if key in self._seen:
                stats["skipped"] += 1
                continue
            if env.timestamp < since:
                stats["skipped"] += 1
                self._seen.add(key)
                continue
            ok = handler(wire, env)
            self._seen.add(key)
            if ok:
                stats["ingested"] += 1
            else:
                stats["failed"] += 1

        file_stats = self._fallback.poll(handler, since=since)
        for k, v in file_stats.items():
            stats[k] = stats.get(k, 0) + int(v)
        return stats