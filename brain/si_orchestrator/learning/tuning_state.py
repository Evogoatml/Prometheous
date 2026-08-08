"""Persistent tuning parameters (loaded by ranking + router)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class TuningParams:
    """Weights the trainer optimizes."""

    # memory ranking
    w_lexical: float = 1.0
    w_tag: float = 1.5
    w_coverage: float = 1.5
    w_recency: float = 2.0
    w_success: float = 1.25
    w_fail_penalty: float = 0.5
    half_life_days: float = 3.0

    # routing
    tool_cue_boost: float = 3.0
    skill_match_weight: float = 1.0
    name_match_weight: float = 2.0
    fail_bias_weight: float = 0.35

    # meta
    version: str = "1.0.0"
    updated_at: float = field(default_factory=time.time)
    train_rounds: int = 0
    best_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TuningParams":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def default_tuning_path(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parents[1]
    return root / "data" / "tuning.json"


def load_tuning(path: Path | str | None = None) -> TuningParams:
    p = Path(path) if path else default_tuning_path()
    if not p.exists():
        return TuningParams()
    try:
        return TuningParams.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return TuningParams()


def save_tuning(params: TuningParams, path: Path | str | None = None) -> Path:
    p = Path(path) if path else default_tuning_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    params.updated_at = time.time()
    p.write_text(json.dumps(params.to_dict(), indent=2) + "\n", encoding="utf-8")
    return p


# Process-wide active params (trainer sets; scorers read)
_ACTIVE: Optional[TuningParams] = None


def set_active_tuning(params: TuningParams) -> None:
    global _ACTIVE
    _ACTIVE = params


def get_active_tuning() -> TuningParams:
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = load_tuning()
    return _ACTIVE
