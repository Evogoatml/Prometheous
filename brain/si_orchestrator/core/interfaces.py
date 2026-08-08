"""
Interface contracts for the SI Orchestrator.

All major subsystems implement these ABCs so backends can be swapped
via the registry without changing core orchestration logic.
Schema version: 1.0.0
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence


SCHEMA_VERSION = "1.0.0"


@dataclass
class MemoryRecord:
    """Canonical memory unit with provenance."""

    id: str
    content: str
    kind: str = "episode"  # episode | fact | rule | embedding_ref
    tags: List[str] = field(default_factory=list)
    score: float = 0.0
    provenance: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: float = 0.0
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class RecallQuery:
    text: str
    tags: List[str] = field(default_factory=list)
    top_k: int = 5
    hybrid: bool = True  # lexical + optional vector later
    min_score: float = 0.0


@dataclass
class AgentTask:
    id: str
    goal: str
    context: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"


@dataclass
class AgentResult:
    task_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    traces: List[Dict[str, Any]] = field(default_factory=list)


class MemoryBackend(ABC):
    """Pluggable memory: Hopfield, vector DB, graph, hybrid, JSON, …"""

    name: str = "memory"
    version: str = "1.0.0"

    @abstractmethod
    def store(self, record: MemoryRecord) -> str:
        """Persist a record; return id."""

    @abstractmethod
    def recall(self, query: RecallQuery) -> List[MemoryRecord]:
        """Retrieve ranked records with provenance."""

    @abstractmethod
    def delete(self, record_id: str) -> bool:
        ...

    def consolidate(self) -> Dict[str, Any]:
        """Optional: merge/decay/forget. Default no-op."""
        return {"status": "noop"}

    def stats(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version}


class LearningStrategy(ABC):
    """Pluggable continual learning / optimization loop."""

    name: str = "learning"
    version: str = "1.0.0"

    @abstractmethod
    def observe(self, experience: Dict[str, Any]) -> None:
        """Ingest one experience (goal, plan, result, feedback)."""

    @abstractmethod
    def improve(self) -> Dict[str, Any]:
        """Run one learning / consolidation step; return metrics."""

    def status(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version}


class SymbolicReasoner(ABC):
    """Rule / symbolic engine (Lisp bridge later)."""

    name: str = "symbolic"
    version: str = "1.0.0"

    @abstractmethod
    def assert_rule(self, rule: str, meta: Optional[Dict[str, Any]] = None) -> str:
        ...

    @abstractmethod
    def query(self, expression: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def list_rules(self) -> List[Dict[str, Any]]:
        ...


class Agent(ABC):
    """Synthetic / specialized agent registered with the orchestrator."""

    name: str = "agent"
    version: str = "1.0.0"
    skills: Sequence[str] = ()

    @abstractmethod
    def run(self, task: AgentTask) -> AgentResult:
        ...

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "skills": list(self.skills),
        }
