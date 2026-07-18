"""
Prometheous hybrid self-healing — log proposals, apply in worktree by default.

Live source edits require PROM_HEALING_LIVE_APPLY=1 plus explicit apply_live().
"""
from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, Optional

from learning.healing.analyzer import FaultLocalizer, FaultReport
from learning.healing.decorators import self_healing
from learning.healing.metalearner import PatchMetaLearner
from learning.healing.patcher import PatchGenerator
from learning.healing.proposal_log import HEALING_DIR, ProposalLog
from learning.healing.validator import PatchValidator

logger = logging.getLogger(__name__)

_localizer = FaultLocalizer()
_patcher = PatchGenerator()
_validator = PatchValidator()
_log = ProposalLog()
_meta = PatchMetaLearner(_log)


def handle_failure(
    exc: BaseException,
    *,
    agent: Optional[str] = None,
    task_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    tb: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze an exception and append a proposal record. Does not modify code.
    """
    fault = _localizer.localize(exc, tb=tb)
    strategy = _meta.get_best_strategy(fault.exc_type)
    proposals = _patcher.generate(fault, preferred_strategy=strategy)

    validated = []
    for proposal in proposals:
        ok, msg = _validator.validate_proposal(proposal)
        entry = proposal.to_dict()
        entry["valid"] = ok
        entry["validation"] = msg
        if ok:
            validated.append(entry)

    record = {
        "agent": agent,
        "task_id": task_id,
        "payload_keys": list((payload or {}).keys()),
        "fault": fault.to_dict(),
        "strategy_used": strategy,
        "proposals": validated,
        "proposal_count": len(validated),
    }
    proposal_id = _log.append(record)
    _meta.record_generation(fault.exc_type, strategy, len(validated) > 0)

    best = validated[0] if validated else None
    return {
        "proposal_id": proposal_id,
        "exc_type": fault.exc_type,
        "message": fault.message,
        "file": fault.primary_file,
        "line": fault.primary_line,
        "best_strategy": best.get("strategy") if best else None,
        "best_description": best.get("description") if best else None,
        "best_diff": best.get("diff") if best else None,
        "log_path": str(_log.path),
    }


def recent_proposals(limit: int = 10) -> list[Dict[str, Any]]:
    return _log.list_recent(limit=limit)


def mark_proposal_helpful(proposal_id: str) -> bool:
    ok = _log.mark_helpful(proposal_id)
    if ok:
        entry = _log.get(proposal_id)
        if entry:
            fault = entry.get("fault") or {}
            strategy = entry.get("strategy_used") or ""
            _meta.record_helpful(fault.get("exc_type", ""), strategy)
    return ok


def healing_summary() -> Dict[str, Any]:
    recent = _log.list_recent(limit=20)
    applied = sum(1 for e in recent if e.get("applied"))
    return {
        "total_proposals": _log.count(),
        "applied_recent": applied,
        "strategies": _meta.summary(),
        "recent": len(recent),
        "mode": "hybrid",
        "worktree_dir": str(HEALING_DIR / "worktrees"),
        "live_gate": "PROM_HEALING_LIVE_APPLY=1",
    }


from learning.healing.hybrid import apply_live, apply_worktree, format_proposal_brief, list_proposals_brief


__all__ = [
    "FaultReport",
    "FaultLocalizer",
    "handle_failure",
    "self_healing",
    "recent_proposals",
    "mark_proposal_helpful",
    "healing_summary",
    "apply_worktree",
    "apply_live",
    "format_proposal_brief",
    "list_proposals_brief",
]