"""
Per-task outcome memory — success rates and timing trends.
Adapted from adaptive_vault learning_core.py.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from utils.config import cfg

DATA_PATH = cfg.DATA_DIR / "learning" / "task_memory.json"
MAX_ENTRIES = 250


class TaskMemory:
    def __init__(self):
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

    def record(self, task: str, result: str, metrics: dict | None = None) -> None:
        entry = {
            "task": task,
            "time": time.time(),
            "result": result,
            "metrics": metrics or {},
        }
        memory = self._load()
        memory.append(entry)
        self._save(memory[-MAX_ENTRIES:])

    def _load(self) -> list:
        if not DATA_PATH.exists():
            return []
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: list) -> None:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def summarize_task(self, task: str) -> dict | None:
        entries = [m for m in self._load() if m["task"] == task]
        if not entries:
            return None
        durations = [
            m["metrics"].get("duration", 0)
            for m in entries
            if m.get("metrics") and m["metrics"].get("duration")
        ]
        avg_time = statistics.mean(durations) if durations else 0.0
        success_rate = sum(1 for m in entries if m["result"] == "success") / len(entries)
        return {
            "runs": len(entries),
            "avg_time": round(avg_time, 4),
            "success_rate": round(success_rate, 2),
        }

    def summarize_all(self) -> dict:
        memory = self._load()
        tasks = {m["task"] for m in memory}
        return {t: self.summarize_task(t) for t in tasks}