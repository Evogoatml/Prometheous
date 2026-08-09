"""Budget tracking for token and USD usage."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

try:
    from utils.config import cfg
    _USAGE_PATH = Path(cfg.DATA_DIR) / "budget" / "usage.json"
except Exception:
    _USAGE_PATH = Path(__file__).resolve().parents[2] / "data" / "budget" / "usage.json"

logger = logging.getLogger(__name__)


class BudgetController:
    """Track usage and recommend cheaper execution paths when needed."""

    def __init__(self, token_budget: int = 1_000_000, usd_budget: float = 10.0) -> None:
        self.token_budget = int(token_budget)
        self.usd_budget = float(usd_budget)
        self.usage_path = _USAGE_PATH
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        self.usage = self._load_usage()
        self.usage.setdefault("token_budget", self.token_budget)
        self.usage.setdefault("usd_budget", self.usd_budget)
        self.usage.setdefault("tokens_used", 0)
        self.usage.setdefault("usd_used", 0.0)
        self.usage.setdefault("agents", {})

    def track_tokens(self, agent: str, tokens: int, model: str = "default") -> None:
        self.usage["tokens_used"] += int(tokens)
        agent_usage = self.usage["agents"].setdefault(agent, {"tokens": 0, "usd": 0.0, "models": {}})
        agent_usage["tokens"] += int(tokens)
        agent_usage["models"][model] = agent_usage["models"].get(model, 0) + int(tokens)
        self._save()

    def track_cost(self, agent: str, usd: float) -> None:
        self.usage["usd_used"] += float(usd)
        agent_usage = self.usage["agents"].setdefault(agent, {"tokens": 0, "usd": 0.0, "models": {}})
        agent_usage["usd"] += float(usd)
        self._save()

    def get_usage(self) -> Dict[str, Any]:
        return dict(self.usage)

    def is_budget_exceeded(self) -> bool:
        return self.usage.get("tokens_used", 0) > self.token_budget or self.usage.get("usd_used", 0.0) > self.usd_budget

    def recommend_cheap_path(self, goal: str) -> str:
        usage_ratio = max(
            self.usage.get("tokens_used", 0) / max(self.token_budget, 1),
            self.usage.get("usd_used", 0.0) / max(self.usd_budget, 0.0001),
        )
        if usage_ratio >= 0.8 or "local" in (goal or "").lower():
            return "local"
        return "llm"

    def estimate_tokens(self, text: str) -> int:
        return max(0, len(text or "") // 4)

    def _load_usage(self) -> Dict[str, Any]:
        if not self.usage_path.exists():
            return {}
        try:
            data = json.loads(self.usage_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        self.usage_path.write_text(json.dumps(self.usage, indent=2, sort_keys=True), encoding="utf-8")
