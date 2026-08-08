"""
Record full agent dispatch trajectories for fine-tuning dataset builds.

Appended to data/learning/trajectories.jsonl on every orchestrator run.
Consumed by brain/cogno/boot/pipeline.py as session_logs source.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from utils.config import cfg

TRAJECTORY_PATH = cfg.DATA_DIR / "learning" / "trajectories.jsonl"
MAX_ENTRIES = 500


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in ("user_msg", "goal", "intent", "skill_name", "query"):
            out[key] = str(value)[:2000]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
    return out


def _safe_result(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result or not isinstance(result, dict):
        return {}
    keep = ("status", "reason", "note", "intent", "skill_name", "error")
    return {k: result[k] for k in keep if k in result}


def record_task(
    *,
    task_id: str,
    intent: str,
    agent: str | None,
    status: str,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    started_at: float | None = None,
    finished_at: float | None = None,
) -> None:
    finished = finished_at or time.time()
    started = started_at or finished
    entry = {
        "task_id": task_id,
        "intent": intent,
        "agent": agent,
        "status": status,
        "success": status == "done",
        "payload": _safe_payload(payload),
        "result": _safe_result(result),
        "error": (error or "")[:500] or None,
        "started_at": started,
        "finished_at": finished,
        "duration": round(finished - started, 6),
        "ts": finished,
    }
    TRAJECTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRAJECTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _trim()


def _trim() -> None:
    if not TRAJECTORY_PATH.exists():
        return
    with open(TRAJECTORY_PATH, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()]
    if len(lines) <= MAX_ENTRIES:
        return
    with open(TRAJECTORY_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines[-MAX_ENTRIES:])