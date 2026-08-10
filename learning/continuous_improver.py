"""
ContinuousImprover — periodically audits execution history and proposes fixes.

Attached at boot as `orchestrator.improver` (see main.py bootstrap). Each
cycle:
  1. Reads recent orchestrator trajectories from data/learning/trajectories.jsonl.
  2. Groups failures by agent and error, ranking recurring problems.
  3. Generates improvement proposals (optimizer recommendations + healing).
  4. Logs the cycle report for observability.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from utils.config import cfg

TRAJECTORY_PATH = cfg.LEARNING_DIR / "trajectories.jsonl"
REPORT_PATH = cfg.LEARNING_DIR / "improver_report.json"
CYCLE_LIMIT = 300


class ContinuousImprover:
    def __init__(self) -> None:
        self.cycles = 0
        self.last_cycle: Optional[Dict[str, Any]] = None

    def read_trajectories(self, limit: int = CYCLE_LIMIT) -> List[Dict[str, Any]]:
        if not TRAJECTORY_PATH.exists():
            return []
        with open(TRAJECTORY_PATH, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        entries: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def analyze(self) -> Dict[str, Any]:
        """Summarize failure patterns across recent trajectories."""
        trajectories = self.read_trajectories()
        failed = [t for t in trajectories if t.get("status") in ("failed", "error")]
        total = len(trajectories)

        by_agent: Dict[str, int] = Counter(t.get("agent") or "?" for t in failed)
        errors: Dict[str, int] = Counter((t.get("error") or "")[:200] or "unknown" for t in failed)

        return {
            "total_tasks": total,
            "failed_tasks": len(failed),
            "failure_rate": round(len(failed) / total, 4) if total else 0.0,
            "failures_by_agent": dict(by_agent.most_common(10)),
            "top_errors": dict(errors.most_common(10)),
            "ts": time.time(),
        }

    def propose_improvements(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Generate concrete improvement suggestions from failures + optimizer."""
        proposals: List[Dict[str, Any]] = []

        analysis = self.analyze()
        for agent_name, count in analysis.get("failures_by_agent", {}).items():
            if count >= 2:
                proposals.append({
                    "type": "agent_review",
                    "target": agent_name,
                    "detail": f"{count} failures observed; review execute() error handling",
                })

        for error, count in list(analysis.get("top_errors", {}).items())[:limit]:
            proposals.append({
                "type": "error_pattern",
                "target": error,
                "detail": f"recurring error x{count}; consider guard/fallback",
            })

        try:
            from learning.optimizer import Optimizer
            recs = Optimizer().generate_recommendations()
            for rec in recs[:limit]:
                proposals.append({"type": "optimizer", "target": "system", "detail": rec})
        except Exception:
            pass

        return proposals[:limit]

    def run_cycle(self) -> Dict[str, Any]:
        """Run one full improvement cycle and persist its report."""
        self.cycles += 1
        analysis = self.analyze()
        proposals = self.propose_improvements()
        report: Dict[str, Any] = {
            "cycle": self.cycles,
            "analysis": analysis,
            "proposals": proposals,
            "ts": time.time(),
        }
        try:
            REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError:
            pass
        self.last_cycle = report
        return report

    def recent_proposals(self, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            from learning.healing import recent_proposals as healing_recent
            return healing_recent(limit=limit)
        except Exception:
            return []

    def summary(self) -> Dict[str, Any]:
        if self.last_cycle is None:
            return {"cycles": self.cycles, "last_cycle": None}
        return {
            "cycles": self.cycles,
            "last_cycle": self.last_cycle["cycle"],
            "last_failure_rate": self.last_cycle["analysis"]["failure_rate"],
            "last_proposals": len(self.last_cycle["proposals"]),
        }
