from swarm.base import BaseAgent
from typing import Any, Dict

from agents.paradox_format import format_paradox_audit

try:
    from paradox.paradox_aware_orchestrator import paradox as paradox_auditor
except Exception:
    paradox_auditor = None


class ParadoxAgent(BaseAgent):
    name = "paradox"
    role = "Paradox"
    specialty = "audit decisions for contradictions and blind spots (brain/paradox layer)"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        ctx = payload or {}
        if paradox_auditor:
            audit = paradox_auditor.audit(ctx)
            out = {
                "status": "ok",
                "agent": self.name,
                "result": audit,
                "message": "Paradox audit complete. See result for contradictions / blind_spots / recommendation.",
            }
            out["formatted"] = format_paradox_audit(out)
            return out
        from paradox.paradox_aware_orchestrator import ParadoxAwareOrchestrator
        auditor = ParadoxAwareOrchestrator()
        audit = auditor.audit(ctx)
        out = {
            "status": "ok",
            "agent": self.name,
            "result": audit,
            "message": "Paradox audit complete.",
        }
        out["formatted"] = format_paradox_audit(out)
        return out