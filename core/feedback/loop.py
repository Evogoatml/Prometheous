"""Feedback persistence and corrective learning hooks."""
from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.config import cfg
    _DATA_DIR = Path(cfg.DATA_DIR)
except Exception:
    _DATA_DIR = Path(__file__).resolve().parents[2] / "data"

logger = logging.getLogger(__name__)


@dataclass
class FeedbackEntry:
    task_id: str
    agent: str
    goal: str
    user_rating: int
    correction: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class FeedbackLoop:
    """Store ratings and fold corrections back into trajectories."""

    def __init__(self) -> None:
        self.feedback_path = _DATA_DIR / "feedback" / "feedback.jsonl"
        self.trajectory_path = _DATA_DIR / "learning" / "trajectories.jsonl"
        self.feedback_path.parent.mkdir(parents=True, exist_ok=True)

    def submit(self, task_id: str, agent: str, goal: str, rating: int, correction: str = None) -> FeedbackEntry:
        entry = FeedbackEntry(
            task_id=task_id,
            agent=agent,
            goal=goal,
            user_rating=max(1, min(5, int(rating))),
            correction=correction,
            timestamp=time.time(),
        )
        with open(self.feedback_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        return entry

    def learn_from_negatives(self, min_rating: int = 2) -> Dict[str, Any]:
        negatives = [entry for entry in self._read_feedback() if int(entry.get("user_rating", 0)) <= min_rating]
        by_agent = Counter(entry.get("agent") or "unknown" for entry in negatives)
        corrections = [str(entry.get("correction") or "") for entry in negatives if entry.get("correction")]
        return {
            "count": len(negatives),
            "agents": dict(by_agent),
            "common_corrections": corrections[:10],
        }

    def refine_trajectory(self, task_id: str, correction: str) -> bool:
        if not self.trajectory_path.exists():
            return False
        updated = False
        lines = [line for line in self.trajectory_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rewritten: List[str] = []
        for line in lines:
            try:
                payload = json.loads(line)
            except Exception:
                rewritten.append(line)
                continue
            if payload.get("task_id") == task_id:
                payload["user_correction"] = correction
                payload["refined"] = True
                updated = True
            rewritten.append(json.dumps(payload, ensure_ascii=False))
        if updated:
            self.trajectory_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        return updated

    def get_stats(self) -> Dict[str, Any]:
        entries = self._read_feedback()
        ratings = Counter(int(entry.get("user_rating", 0)) for entry in entries)
        by_agent: Dict[str, List[int]] = defaultdict(list)
        for entry in entries:
            by_agent[str(entry.get("agent") or "unknown")].append(int(entry.get("user_rating", 0)))
        trends = {
            agent: round(sum(values) / len(values), 4)
            for agent, values in by_agent.items() if values
        }
        return {"total": len(entries), "ratings": dict(ratings), "average_by_agent": trends}

    def _read_feedback(self) -> List[Dict[str, Any]]:
        if not self.feedback_path.exists():
            return []
        items: List[Dict[str, Any]] = []
        for line in self.feedback_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                logger.warning("skipping invalid feedback line")
        return items
