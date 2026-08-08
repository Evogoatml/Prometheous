"""
Hybrid healing API — log + optional worktree/live apply.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from learning.healing.applier import HybridApplier
from learning.healing.metalearner import PatchMetaLearner
from learning.healing.proposal_log import ProposalLog

_log = ProposalLog()
_applier = HybridApplier()
_meta = PatchMetaLearner(_log)


def apply_worktree(proposal_id: str, *, proposal_index: int = 0) -> Dict[str, Any]:
    entry = _log.get(proposal_id)
    if not entry:
        return {"status": "error", "error": f"unknown proposal: {proposal_id}"}
    result = _applier.apply_from_log_entry(entry, proposal_index=proposal_index, live=False)
    if result.get("status") == "ok":
        _log.mark_applied(proposal_id, result)
    return result


def apply_live(proposal_id: str, *, proposal_index: int = 0) -> Dict[str, Any]:
    entry = _log.get(proposal_id)
    if not entry:
        return {"status": "error", "error": f"unknown proposal: {proposal_id}"}
    result = _applier.apply_from_log_entry(entry, proposal_index=proposal_index, live=True)
    if result.get("status") in ("ok", "warning"):
        _log.mark_applied(proposal_id, result)
        _log.mark_helpful(proposal_id)
        entry = _log.get(proposal_id)
        if entry:
            fault = entry.get("fault") or {}
            _meta.record_helpful(fault.get("exc_type", ""), entry.get("strategy_used", ""))
    return result


def format_proposal_brief(entry: Dict[str, Any]) -> str:
    fault = entry.get("fault") or {}
    props = entry.get("proposals") or []
    best = props[0] if props else {}
    applied = entry.get("applied") or {}
    lines = [
        f"ID: {entry.get('id')}",
        f"Agent: {entry.get('agent', '?')}",
        f"Error: {fault.get('exc_type')}: {fault.get('message', '')[:80]}",
        f"File: {fault.get('primary_file', '?')}:{fault.get('primary_line', '?')}",
        f"Strategy: {best.get('strategy', '?')}",
        f"Fix: {best.get('description', '?')}",
    ]
    if applied:
        lines.append(f"Applied ({applied.get('mode')}): {applied.get('worktree_path') or applied.get('applied_path')}")
    return "\n".join(lines)


def list_proposals_brief(limit: int = 5) -> str:
    entries = _log.list_recent(limit=limit)
    if not entries:
        return "No healing proposals yet."
    blocks = []
    for e in entries:
        blocks.append(format_proposal_brief(e))
        blocks.append("---")
    return "\n".join(blocks)