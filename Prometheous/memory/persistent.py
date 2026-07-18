"""
Persistent conversation memory — SQLite-backed drop-in for ConversationStore.

Same interface as memory.conversation.ConversationStore so call sites can
swap by import. Backed by a dedicated table `persistent_conversations` in
data/brain.db (the file already used by data/memory_sqlite.py and core/decision).

Schema (one row per turn):
    chat_id      INTEGER  -- Telegram chat_id, or 0 for REPL, or hashed for CLI
    role         TEXT     -- "user" | "assistant" | "system" | "tool"
    content      TEXT     -- the message body
    ts           REAL     -- unix timestamp
    metadata     TEXT     -- JSON blob (intent, agent, confidence, etc.)

Indexes: (chat_id, ts DESC) for fast recent-history queries.

Thread safety: sqlite3 connection is opened with check_same_thread=False
and guarded by a re-entrant lock. This matters because Telegram runs
the polling loop on a worker thread and REPL writes from the main thread.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.config import cfg


# ---------- public dataclass (mirrors memory.conversation) -------------- #

@dataclass
class PersistentEntry:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PersistentMemory:
    """Per-chat_id memory with the same shape as ConversationMemory."""

    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.last_target: Optional[str] = None
        self.last_plan: Optional[Dict[str, Any]] = None
        self.tool_results: List[str] = []
        # history is hydrated on demand; cached locally for the process lifetime
        self._history_cache: List[PersistentEntry] = []
        self._hydrated = False

    def add(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        entry = PersistentEntry(role=role, content=content, metadata=metadata or {})
        self._history_cache.append(entry)
        _store.write(self.chat_id, entry)

    def get_history(self, limit: int = 20) -> List[Dict[str, str]]:
        if not self._hydrated:
            self._history_cache = _store.read(self.chat_id, limit=limit)
            self._hydrated = True
        # Refresh cache if the call asks for more than we have cached
        if limit > len(self._history_cache):
            self._history_cache = _store.read(self.chat_id, limit=limit)
        return [{"role": e.role, "content": e.content} for e in self._history_cache[-limit:]]

    def add_tool_result(self, tool: str, result: str) -> None:
        self.tool_results.append(f"[{tool}]\n{result}")

    def clear(self) -> None:
        self._history_cache.clear()
        self._hydrated = True
        self.last_target = None
        self.last_plan = None
        self.tool_results.clear()
        _store.clear(self.chat_id)


class PersistentConversationStore:
    """Process-wide store of per-chat_id PersistentMemory handles."""

    def __init__(self):
        self._conversations: Dict[int, PersistentMemory] = {}
        self._lock = threading.Lock()

    def get(self, chat_id: int) -> PersistentMemory:
        with self._lock:
            if chat_id not in self._conversations:
                self._conversations[chat_id] = PersistentMemory(chat_id)
            return self._conversations[chat_id]

    def clear(self, chat_id: int) -> None:
        with self._lock:
            if chat_id in self._conversations:
                self._conversations[chat_id].clear()
                del self._conversations[chat_id]


# ---------- internal SQLite layer --------------------------------------- #

_SCHEMA = """
CREATE TABLE IF NOT EXISTS persistent_conversations (
    chat_id  INTEGER NOT NULL,
    role     TEXT    NOT NULL,
    content  TEXT    NOT NULL,
    ts       REAL    NOT NULL,
    metadata TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_persistent_conv_chat_ts
    ON persistent_conversations (chat_id, ts DESC);
"""


class _PersistentStore:
    """Single SQLite connection, schema bootstrap, and the 3 ops callers need."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def write(self, chat_id: int, entry: PersistentEntry) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO persistent_conversations (chat_id, role, content, ts, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    chat_id,
                    entry.role,
                    entry.content,
                    entry.timestamp,
                    json.dumps(entry.metadata or {}),
                ),
            )
            self._conn.commit()

    def read(self, chat_id: int, limit: int = 20) -> List[PersistentEntry]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT role, content, ts, metadata FROM persistent_conversations "
                "WHERE chat_id = ? ORDER BY ts DESC LIMIT ?",
                (chat_id, limit),
            )
            rows = cur.fetchall()
        # Returned DESC from DB; flip to ASC so callers see chronological order
        out: List[PersistentEntry] = []
        for role, content, ts, meta_json in reversed(rows):
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except json.JSONDecodeError:
                meta = {}
            out.append(PersistentEntry(role=role, content=content, timestamp=ts, metadata=meta))
        return out

    def clear(self, chat_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM persistent_conversations WHERE chat_id = ?", (chat_id,)
            )
            self._conn.commit()


# Module-level singleton, wired to the same brain.db the rest of the system uses.
_store = _PersistentStore(cfg.SQLITE_PATH)

# Public singleton mirroring ConversationStore's API.
store = PersistentConversationStore()
