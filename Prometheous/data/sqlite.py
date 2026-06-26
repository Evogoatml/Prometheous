
"""
SQLite store — thin wrapper around sqlite3. Most callers should use
core.memory.knowledge directly. This module exists for cases where
you need a fresh connection (migrations, bulk imports, etc.).
"""
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, List, Tuple

from utils.config import cfg


class SQLiteStore:
    def __init__(self, path: str = None):
        self.path = path or cfg.SQLITE_PATH
        self._lock = threading.Lock()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(sql, params)

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[Tuple]:
        with self._lock, self.connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall()


store = SQLiteStore()
