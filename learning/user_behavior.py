"""
User behavior logging — records what actions users trigger and how they land.

Interface:
    from learning import user_behavior
    user_behavior.record("learn_topic", "success")

Records are appended to data/learning/user_behavior.jsonl and can be
aggregated into per-action summaries.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from utils.config import cfg

BEHAVIOR_LOG = cfg.LEARNING_DIR / "user_behavior.jsonl"


def record(action: str, result: str = "success", **extra: Any) -> Dict[str, Any]:
    """Append one user-triggered action to the behavior ledger."""
    entry: Dict[str, Any] = {
        "action": str(action),
        "result": str(result),
        "ts": time.time(),
        **extra,
    }
    cfg.LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    with open(BEHAVIOR_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def recent(limit: int = 200) -> List[Dict[str, Any]]:
    """Return the most recent behavior records."""
    if not BEHAVIOR_LOG.exists():
        return []
    with open(BEHAVIOR_LOG, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()]
    entries: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def summary(limit: int = 1000) -> Dict[str, Any]:
    """Aggregate behavior counts by action and result."""
    entries = recent(limit=limit)
    by_action: Counter[str] = Counter(e.get("action") or "?" for e in entries)
    by_result: Counter[str] = Counter(e.get("result") or "?" for e in entries)
    return {
        "total": len(entries),
        "by_action": dict(by_action.most_common()),
        "by_result": dict(by_result.most_common()),
    }
