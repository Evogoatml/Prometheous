"""Explicit reasoning trace persistence for debugging and analysis."""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    from utils.config import cfg
    _TRACE_PATH = Path(cfg.DATA_DIR) / "reasoning" / "traces.jsonl"
except Exception:
    _TRACE_PATH = Path(__file__).resolve().parents[2] / "data" / "reasoning" / "traces.jsonl"

logger = logging.getLogger(__name__)


@dataclass
class DecisionPoint:
    step: str
    alternatives: List[str] = field(default_factory=list)
    chosen: str = ""
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ReasoningTrace:
    trace_id: str
    goal: str
    decisions: List[DecisionPoint] = field(default_factory=list)
    final_answer: Optional[str] = None
    created_at: float = field(default_factory=time.time)


class ReasoningRecorder:
    """Singleton recorder that stores reasoning traces in memory and JSONL."""

    _instance: Optional["ReasoningRecorder"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.path = _TRACE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.traces: Dict[str, ReasoningTrace] = {}
        self._load_recent()
        self._initialized = True

    def start_trace(self, goal: str) -> str:
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
        self.traces[trace_id] = ReasoningTrace(trace_id=trace_id, goal=goal)
        return trace_id

    def record_decision(self, trace_id: str, step: str, alternatives: List[str], chosen: str, reason: str) -> None:
        trace = self.traces.get(trace_id)
        if trace is None:
            trace = ReasoningTrace(trace_id=trace_id, goal="unknown")
            self.traces[trace_id] = trace
        trace.decisions.append(DecisionPoint(step=step, alternatives=list(alternatives or []), chosen=chosen, reason=reason))

    def finish_trace(self, trace_id: str, answer: str) -> ReasoningTrace:
        trace = self.traces.get(trace_id)
        if trace is None:
            trace = ReasoningTrace(trace_id=trace_id, goal="unknown")
            self.traces[trace_id] = trace
        trace.final_answer = answer
        self._append(trace)
        return trace

    def get_trace(self, trace_id: str) -> Optional[ReasoningTrace]:
        return self.traces.get(trace_id)

    def _append(self, trace: ReasoningTrace) -> None:
        payload = asdict(trace)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _load_recent(self, limit: int = 200) -> None:
        if not self.path.exists():
            return
        try:
            lines = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for line in lines[-limit:]:
                payload = json.loads(line)
                decisions = [DecisionPoint(**entry) for entry in payload.get("decisions", [])]
                payload["decisions"] = decisions
                trace = ReasoningTrace(**payload)
                self.traces[trace.trace_id] = trace
        except Exception as exc:
            logger.warning("failed to load reasoning traces: %s", exc)
