"""
Training + tuning loop for Prometheous SI.

Runs curriculum scenarios, scores outcomes, hill-climbs TuningParams,
persists best config to data/tuning.json, consolidates memory (sleep).
"""

from __future__ import annotations

import copy
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.orchestrator import SIOrchestrator
from .curriculum import Scenario, default_curriculum, eval_scenario
from .tuning_state import (
    TuningParams,
    get_active_tuning,
    load_tuning,
    save_tuning,
    set_active_tuning,
)


@dataclass
class TrainReport:
    epochs: int
    scenarios: int
    baseline_score: float
    final_score: float
    best_score: float
    best_params: Dict[str, Any]
    history: List[Dict[str, Any]] = field(default_factory=list)
    scenario_scores: List[Dict[str, Any]] = field(default_factory=list)
    path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epochs": self.epochs,
            "scenarios": self.scenarios,
            "baseline_score": self.baseline_score,
            "final_score": self.final_score,
            "best_score": self.best_score,
            "best_params": self.best_params,
            "history": self.history,
            "scenario_scores": self.scenario_scores,
            "path": self.path,
        }


def _weighted_mean(results: List[Dict[str, Any]]) -> float:
    num = sum(r["weighted_score"] for r in results)
    den = sum(r["weight"] for r in results) or 1.0
    return num / den


def run_curriculum(
    orch: SIOrchestrator,
    scenarios: List[Scenario],
) -> Tuple[float, List[Dict[str, Any]]]:
    results = []
    for sc in scenarios:
        cycle = orch.run(sc.goal)
        ev = eval_scenario(sc, cycle.to_dict())
        results.append(ev)
    return _weighted_mean(results), results


def _perturb(params: TuningParams, scale: float = 0.15) -> TuningParams:
    """Random local search step on continuous weights."""
    p = TuningParams.from_dict(params.to_dict())
    fields = [
        "w_lexical",
        "w_tag",
        "w_coverage",
        "w_recency",
        "w_success",
        "w_fail_penalty",
        "half_life_days",
        "tool_cue_boost",
        "skill_match_weight",
        "name_match_weight",
        "fail_bias_weight",
    ]
    for name in fields:
        cur = getattr(p, name)
        if not isinstance(cur, (int, float)):
            continue
        delta = cur * scale * random.uniform(-1.0, 1.0)
        if abs(cur) < 1e-6:
            delta = scale * random.uniform(-1.0, 1.0)
        new = max(0.05, cur + delta)
        # keep fail penalty reasonable
        if name == "w_fail_penalty":
            new = min(new, 3.0)
        if name == "half_life_days":
            new = min(max(new, 0.25), 30.0)
        if name == "tool_cue_boost":
            new = min(max(new, 0.5), 8.0)
        setattr(p, name, float(new))
    return p


def train(
    *,
    epochs: int = 5,
    base_dir: Path | None = None,
    scenarios: Optional[List[Scenario]] = None,
    seed: int = 42,
    persist: bool = True,
    verbose: bool = True,
) -> TrainReport:
    """
    Train/tune Prometheous SI.

    Each epoch:
      1. evaluate curriculum under current params
      2. try a perturbed param set
      3. keep better set
      4. sleep_cycle consolidate via learning coordinator if present
    """
    random.seed(seed)
    root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[1]
    scenarios = scenarios or default_curriculum()

    from ..bootstrap import build_orchestrator

    params = load_tuning(root / "data" / "tuning.json")
    set_active_tuning(params)
    orch = build_orchestrator(base_dir=root)

    if verbose:
        print(f"=== Prometheous SI train ===")
        print(f"base_dir={root}")
        print(f"epochs={epochs} scenarios={len(scenarios)} seed={seed}")
        print(f"agents={orch.status()['registry']['agents']}")

    baseline, _ = run_curriculum(orch, scenarios)
    best_score = baseline
    best_params = TuningParams.from_dict(params.to_dict())
    history: List[Dict[str, Any]] = [
        {"epoch": 0, "phase": "baseline", "score": baseline}
    ]

    if verbose:
        print(f"baseline score: {baseline:.3f}")

    last_detail: List[Dict[str, Any]] = []

    for epoch in range(1, epochs + 1):
        # evaluate current
        set_active_tuning(params)
        score_cur, detail_cur = run_curriculum(orch, scenarios)

        # candidate
        cand = _perturb(params)
        set_active_tuning(cand)
        # rebuild orch so fresh learning buffer but same memory file
        orch_c = build_orchestrator(base_dir=root)
        score_cand, detail_cand = run_curriculum(orch_c, scenarios)

        improved = score_cand >= score_cur
        if improved:
            params = cand
            score_cur = score_cand
            detail_cur = detail_cand
            orch = orch_c

        if score_cur > best_score:
            best_score = score_cur
            best_params = TuningParams.from_dict(params.to_dict())

        # sleep / consolidate
        sleep_info = None
        coord = getattr(orch.registry, "_learning_coordinator", None)
        if coord is not None:
            try:
                sleep_info = coord.sleep_cycle()
            except Exception as exc:  # noqa: BLE001
                sleep_info = {"status": "error", "error": str(exc)}

        hist = {
            "epoch": epoch,
            "score": score_cur,
            "candidate_accepted": improved,
            "best_score": best_score,
            "sleep": sleep_info,
        }
        history.append(hist)
        last_detail = detail_cur

        if verbose:
            mark = "↑" if improved else "·"
            print(
                f"epoch {epoch}/{epochs} {mark} score={score_cur:.3f} "
                f"best={best_score:.3f}"
            )
            for d in detail_cur:
                print(
                    f"  [{d['scenario_id']}] {d['score']:.2f} "
                    f"agent={d.get('agent')} parts={d.get('parts')}"
                )

    # finalize best
    best_params.train_rounds = params.train_rounds + epochs
    best_params.best_score = best_score
    set_active_tuning(best_params)
    path = None
    if persist:
        path = str(save_tuning(best_params, root / "data" / "tuning.json"))
        # also write report
        report_path = root / "data" / "train_report.json"
        # final eval under best
        set_active_tuning(best_params)
        orch_f = build_orchestrator(base_dir=root)
        final_score, final_detail = run_curriculum(orch_f, scenarios)
        last_detail = final_detail
    else:
        final_score = best_score

    report = TrainReport(
        epochs=epochs,
        scenarios=len(scenarios),
        baseline_score=baseline,
        final_score=final_score if persist else score_cur,
        best_score=best_score,
        best_params=best_params.to_dict(),
        history=history,
        scenario_scores=last_detail,
        path=path,
    )

    if persist:
        report_path = root / "data" / "train_report.json"
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        if verbose:
            print(f"saved tuning → {path}")
            print(f"saved report → {report_path}")
            print(
                f"done: baseline={baseline:.3f} → final={report.final_score:.3f} "
                f"(best={best_score:.3f})"
            )

    return report
