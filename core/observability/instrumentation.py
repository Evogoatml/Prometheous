"""Structured telemetry spans, metrics, and logs."""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Span:
    span_id: str
    trace_id: str
    operation: str
    start: float
    end: Optional[float] = None
    tags: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"


class Telemetry:
    """Singleton telemetry collector with bounded in-memory spans."""

    _instance: Optional["Telemetry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.spans: List[Span] = []
        self._initialized = True

    def start_span(self, operation: str, trace_id: str = None) -> Span:
        trace = trace_id or f"trace-{uuid.uuid4().hex[:12]}"
        span = Span(span_id=f"span-{uuid.uuid4().hex[:12]}", trace_id=trace, operation=operation, start=time.time())
        self.spans.append(span)
        self.spans = self.spans[-1000:]
        return span

    def end_span(self, span: Span, status: str = "ok", tags: Dict[str, Any] = None) -> Span:
        span.end = time.time()
        span.status = status
        if tags:
            span.tags.update(tags)
        self.structured_log("info", "span_finished", kind="span", span=asdict(span))
        return span

    def emit_metric(self, name: str, value: float, labels: Dict[str, Any] = None) -> None:
        self.structured_log("info", "metric", kind="metric", metric=name, value=value, labels=labels or {})

    def structured_log(self, level: str, msg: str, **kwargs: Any) -> None:
        payload = {"message": msg, **kwargs}
        log_fn = getattr(logger, level.lower(), logger.info)
        log_fn(json.dumps(payload, sort_keys=True, default=str))
