"""
Prometheous global state.

Single dataclass instance shared by core/ and swarm/. Persists to JSON.
"""
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List

from utils.config import cfg


@dataclass
class State:
    # Identity
    boot_id: str = ""
    online_since: float = 0.0
    genesis_complete: bool = False

    # Self-model
    capability_map: Dict[str, Any] = field(default_factory=dict)
    knowledge_gaps: List[str] = field(default_factory=list)
    coherence_score: float = 0.0

    # Current work
    active_goals: List[str] = field(default_factory=list)
    active_tasks: List[Dict[str, Any]] = field(default_factory=list)
    active_agents: List[str] = field(default_factory=list)

    # Metrics
    total_tasks_completed: int = 0
    total_swarms_deployed: int = 0
    total_llm_calls: int = 0
    uptime_cycles: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self) -> None:
        Path(cfg.STATE_PATH).write_text(json.dumps(self.to_dict(), indent=2, default=str))

    def load(self) -> None:
        p = Path(cfg.STATE_PATH)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text())
            for k, v in data.items():
                if hasattr(self, k):
                    setattr(self, k, v)
        except Exception:
            pass


# Single shared instance
state = State()
state.load()
