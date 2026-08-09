"""Rule-based world model for outcome prediction and simulation."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

try:
    from utils.config import cfg
    _WEIGHTS_PATH = Path(cfg.DATA_DIR) / "learning" / "weights.json"
except Exception:
    _WEIGHTS_PATH = Path(__file__).resolve().parents[2] / "data" / "learning" / "weights.json"

logger = logging.getLogger(__name__)


@dataclass
class Prediction:
    success_prob: float
    estimated_cost_usd: float
    estimated_latency_s: float
    risks: List[str] = field(default_factory=list)
    confidence: float = 0.0


class WorldModel:
    """Predict likely outcomes from rules and historical weights."""

    def __init__(self) -> None:
        self.weights = self._load_weights()

    def predict(self, goal: str, agent: str, context: Dict[str, Any]) -> Prediction:
        goal_text = (goal or "").lower()
        ctx = context or {}
        risks: List[str] = []
        base = float(self.weights.get(agent, 0.6))
        if any(keyword in goal_text for keyword in ["delete", "migrate", "deploy", "production"]):
            risks.append("high-impact operation")
            base -= 0.15
        if any(keyword in goal_text for keyword in ["urgent", "asap", "immediately"]):
            risks.append("time pressure")
            base -= 0.05
        if ctx.get("missing_dependencies"):
            risks.append("missing dependencies")
            base -= 0.1
        if ctx.get("tests_present") is False:
            risks.append("no tests present")
            base -= 0.05
        estimated_latency = max(1.0, round(len(goal_text.split()) * 0.6 + (5.0 if risks else 0.0), 2))
        estimated_cost = round(0.01 + (len(goal_text) / 1000.0) + max(0, len(risks) - 1) * 0.02, 4)
        success_prob = max(0.05, min(0.99, round(base, 4)))
        confidence = max(0.2, min(0.95, round(0.7 - (len(risks) * 0.1) + (0.1 if agent in self.weights else 0.0), 4)))
        return Prediction(
            success_prob=success_prob,
            estimated_cost_usd=estimated_cost,
            estimated_latency_s=estimated_latency,
            risks=risks,
            confidence=confidence,
        )

    def simulate_plan(self, steps: List[Dict[str, Any]]) -> List[Prediction]:
        predictions: List[Prediction] = []
        for step in steps or []:
            predictions.append(
                self.predict(
                    goal=str(step.get("goal") or step.get("task") or ""),
                    agent=str(step.get("agent") or "unknown"),
                    context=dict(step.get("context") or {}),
                )
            )
        return predictions

    def should_execute(self, prediction: Prediction, threshold: float = 0.3) -> bool:
        return prediction.success_prob > float(threshold)

    @staticmethod
    def _load_weights() -> Dict[str, float]:
        if not _WEIGHTS_PATH.exists():
            return {}
        try:
            data = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("failed to load world model weights: %s", exc)
            return {}
