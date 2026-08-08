"""
Track which patch strategies work per exception type.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

from learning.healing.proposal_log import HEALING_DIR, ProposalLog

STATS_PATH = HEALING_DIR / "strategy_stats.json"


class PatchMetaLearner:
    def __init__(self, log: ProposalLog) -> None:
        self._log = log
        self._stats = self._load()

    def _load(self) -> Dict[str, Any]:
        HEALING_DIR.mkdir(parents=True, exist_ok=True)
        if STATS_PATH.exists():
            try:
                return json.loads(STATS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"by_exc": {}, "generations": 0}

    def _save(self) -> None:
        STATS_PATH.write_text(json.dumps(self._stats, indent=2), encoding="utf-8")

    def get_best_strategy(self, exc_type: str) -> str:
        bucket = self._stats.get("by_exc", {}).get(exc_type, {})
        if not bucket:
            return self._default_for(exc_type)

        ranked = sorted(
            bucket.items(),
            key=lambda kv: (kv[1].get("helpful", 0), kv[1].get("generated", 0)),
            reverse=True,
        )
        return ranked[0][0] if ranked else self._default_for(exc_type)

    def record_generation(self, exc_type: str, strategy: str, had_valid: bool) -> None:
        by_exc = self._stats.setdefault("by_exc", {})
        bucket = by_exc.setdefault(exc_type, {})
        row = bucket.setdefault(strategy, {"generated": 0, "helpful": 0, "valid": 0})
        row["generated"] += 1
        if had_valid:
            row["valid"] += 1
        self._stats["generations"] = int(self._stats.get("generations", 0)) + 1
        self._save()

    def record_helpful(self, exc_type: str, strategy: str) -> None:
        by_exc = self._stats.setdefault("by_exc", {})
        bucket = by_exc.setdefault(exc_type, {})
        row = bucket.setdefault(strategy, {"generated": 0, "helpful": 0, "valid": 0})
        row["helpful"] += 1
        self._save()

    def summary(self) -> Dict[str, Any]:
        return {
            "generations": self._stats.get("generations", 0),
            "by_exc": self._stats.get("by_exc", {}),
        }

    def _default_for(self, exc_type: str) -> str:
        defaults = {
            "AttributeError": "attribute_guard",
            "KeyError": "dict_get",
            "TypeError": "none_guard",
            "ModuleNotFoundError": "import_fix",
            "ImportError": "import_fix",
            "FileNotFoundError": "path_guard",
            "IndexError": "index_guard",
        }
        return defaults.get(exc_type, "generic_try_except")