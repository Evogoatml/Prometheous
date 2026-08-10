"""
Learner — records per-agent outcomes and tunes swarm behavior.

Interface used by core/orchestrator.py:
    from learning import learner
    learner.record_outcome(agent, success=..., error=..., latency=..., context=...)
    learner.auto_tune()                      # called periodically

Outcomes are appended to data/learning/outcomes.jsonl. The optimizer in
learning/optimizer.py owns the actual tuning logic; this module is the
outcome ledger + thin adapter on top of it.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from utils.config import cfg

OUTCOMES_LOG = cfg.LEARNING_DIR / "outcomes.jsonl"


class Learner:
    def __init__(self) -> None:
        cfg.LEARNING_DIR.mkdir(parents=True, exist_ok=True)

    def record_outcome(
        self,
        agent: str,
        *,
        success: bool = True,
        error: Optional[str] = None,
        latency: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Append one agent execution outcome to the JSONL ledger."""
        entry: Dict[str, Any] = {
            "agent": str(agent),
            "success": bool(success),
            "error": (error or "")[:500] or None,
            "latency_ms": round(float(latency), 3) if latency is not None else None,
            "context": context or {},
            "ts": time.time(),
        }
        with open(OUTCOMES_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def outcomes(self, agent: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        """Return recent outcomes, optionally filtered by agent name."""
        if not OUTCOMES_LOG.exists():
            return []
        with open(OUTCOMES_LOG, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        entries: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if agent:
            entries = [e for e in entries if e.get("agent") == agent]
        return entries

    def success_rate(self, agent: Optional[str] = None) -> float:
        entries = self.outcomes(agent=agent, limit=1000)
        if not entries:
            return 0.0
        return sum(1 for e in entries if e.get("success")) / len(entries)

    def agent_rankings(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Rank agents by success rate with volume weighting."""
        stats: Dict[str, Dict[str, int]] = {}
        for e in self.outcomes(limit=2000):
            name = e.get("agent") or "?"
            s = stats.setdefault(name, {"ok": 0, "total": 0})
            s["total"] += 1
            if e.get("success"):
                s["ok"] += 1
        ranked = sorted(
            (
                {"agent": n, "success_rate": round(s["ok"] / s["total"], 4), "total": s["total"]}
                for n, s in stats.items() if s["total"] > 0
            ),
            key=lambda r: (r["success_rate"], r["total"]),
            reverse=True,
        )
        return ranked[:limit]

    def auto_tune(self) -> Dict[str, Any]:
        """Delegate to the optimizer's load-based auto_tune."""
        try:
            from learning.optimizer import Optimizer
            return Optimizer().auto_tune()
        except Exception as exc:
            return {"status": "skipped", "reason": f"optimizer unavailable: {exc}"}

    def summary(self) -> Dict[str, Any]:
        return {
            "outcomes_logged": len(self.outcomes()),
            "rankings": self.agent_rankings(),
            "tuning": self.auto_tune(),
        }


learner = Learner()
