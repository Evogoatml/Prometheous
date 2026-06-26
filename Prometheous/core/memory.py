"""
Prometheous memory — conversations, knowledge, snapshots.

- ConversationStore: in-process per-chat history (with persistence hook)
- KnowledgeBase: simple dict-based fact store with optional sqlite backup
- Vault: encrypted secrets storage (kept from old memory/vault.py)
"""
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.config import cfg
from utils.helpers import generate_id, timestamp

logger = logging.getLogger(__name__)


# --- Conversation memory -------------------------------------------------

@dataclass
class ConversationEntry:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConversationMemory:
    def __init__(self, chat_id: int, limit: int = 20):
        self.chat_id = chat_id
        self.limit = limit
        self.history: List[ConversationEntry] = []
        self.tool_results: List[str] = []

    def add(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        self.history.append(ConversationEntry(role=role, content=content, metadata=metadata or {}))
        if len(self.history) > self.limit * 2:
            self.history = self.history[-self.limit :]

    def add_tool_result(self, tool: str, result: str):
        self.tool_results.append(f"[{tool}]\n{result}")

    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        n = limit or self.limit
        return [{"role": e.role, "content": e.content} for e in self.history[-n:]]

    def clear(self):
        self.history.clear()
        self.tool_results.clear()


class ConversationStore:
    def __init__(self):
        self.conversations: Dict[int, ConversationMemory] = {}

    def get(self, chat_id: int) -> ConversationMemory:
        if chat_id not in self.conversations:
            self.conversations[chat_id] = ConversationMemory(chat_id, cfg.CONVERSATION_HISTORY_LIMIT)
        return self.conversations[chat_id]

    def drop(self, chat_id: int):
        self.conversations.pop(chat_id, None)


# --- Knowledge base ------------------------------------------------------

class KnowledgeBase:
    """
    Simple in-memory knowledge graph + sqlite persistence.
    Facts stored as (key, value) with tags and timestamp.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or cfg.SQLITE_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                tags TEXT,
                source TEXT,
                created_at REAL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS memory (
                user_id TEXT,
                input TEXT,
                output TEXT,
                ts REAL
            )"""
        )
        self._conn.commit()

    def put(self, key: str, value: Any, tags: Optional[List[str]] = None, source: str = "system") -> str:
        fid = generate_id("f-")
        self._conn.execute(
            "INSERT INTO facts (id, key, value, tags, source, created_at) VALUES (?,?,?,?,?,?)",
            (fid, key, json.dumps(value, default=str), json.dumps(tags or []), source, time.time()),
        )
        self._conn.commit()
        return fid

    def get(self, key: str) -> Optional[Any]:
        cur = self._conn.execute("SELECT value FROM facts WHERE key=? ORDER BY created_at DESC LIMIT 1", (key,))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return row[0]

    def search(self, tag: str, limit: int = 20) -> List[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT key, value, source, created_at FROM facts WHERE tags LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f'%"{tag}"%', limit),
        )
        return [
            {"key": r[0], "value": json.loads(r[1]) if r[1] else None, "source": r[2], "created_at": r[3]}
            for r in cur.fetchall()
        ]

    def record_exchange(self, user_id: str, user_msg: str, assistant_msg: str):
        self._conn.execute(
            "INSERT INTO memory (user_id, input, output, ts) VALUES (?,?,?,?)",
            (user_id, user_msg, assistant_msg, time.time()),
        )
        self._conn.commit()

    def get_history(self, user_id: str, limit: int = 10) -> List[tuple]:
        cur = self._conn.execute(
            "SELECT input, output, ts FROM memory WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        )
        return cur.fetchall()


# --- Encrypted vault -----------------------------------------------------

class EncryptedVault:
    """
    AES-GCM encrypted secret store. Lazy-imports cryptography.
    """

    def __init__(self, vault_dir: Optional[str] = None):
        import base64
        import os as _os
        import secrets as _secrets
        from utils.config import cfg as _cfg

        self._vault_dir = Path(vault_dir or _cfg.VAULT_DIR)
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._key_path = self._vault_dir / ".vault.key"
        self._data_path = self._vault_dir / "vault.enc"

        self._b64 = base64
        self._os = _os
        self._secrets = _secrets
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes()
        key = self._secrets.token_bytes(32)
        self._key_path.write_bytes(key)
        try:
            self._key_path.chmod(0o600)
        except OSError:
            pass
        return key

    def store(self, key_name: str, value: Any) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        data = json.dumps({"key": key_name, "value": value}, default=str).encode()
        nonce = self._secrets.token_bytes(12)
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        envelope = {
            "nonce": self._b64.b64encode(nonce).decode(),
            "ciphertext": self._b64.b64encode(ciphertext).decode(),
        }
        # load existing
        all_entries = self._read_all()
        all_entries[key_name] = envelope
        self._write_all(all_entries)

    def fetch(self, key_name: str) -> Optional[Any]:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        all_entries = self._read_all()
        env = all_entries.get(key_name)
        if not env:
            return None
        try:
            nonce = self._b64.b64decode(env["nonce"])
            ciphertext = self._b64.b64decode(env["ciphertext"])
            aesgcm = AESGCM(self._key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return json.loads(plaintext)["value"]
        except Exception as e:
            logger.error("vault fetch failed for %s: %s", key_name, e)
            return None

    def _read_all(self) -> Dict[str, Any]:
        if not self._data_path.exists():
            return {}
        try:
            return json.loads(self._data_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_all(self, data: Dict[str, Any]) -> None:
        self._data_path.write_text(json.dumps(data, indent=2))
        try:
            self._data_path.chmod(0o600)
        except OSError:
            pass


# --- Single shared instances --------------------------------------------
conversations = ConversationStore()
knowledge = KnowledgeBase()
vault = EncryptedVault()
