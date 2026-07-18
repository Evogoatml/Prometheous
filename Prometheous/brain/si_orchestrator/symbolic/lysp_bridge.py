"""
LYSP / Lisp bridge placeholder.

Phase 1: does not embed a Lisp runtime. Exposes the same surface we will
wrap around an embedded interpreter (clisp / femtolisp / custom LYSP).

All symbolic traffic still goes through SymbolicReasoner ABC.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.interfaces import SymbolicReasoner
from .rules import RuleSymbolicReasoner


class LyspBridge(SymbolicReasoner):
    """
    Facade: today delegates to RuleSymbolicReasoner.
    Tomorrow: eval(expr) via FFI into LYSP and map results to query().
    """

    name = "lysp_bridge"
    version = "0.1.0-stub"

    def __init__(self, fallback: Optional[SymbolicReasoner] = None):
        self.fallback = fallback or RuleSymbolicReasoner()
        self.backend = "python_rules"  # → "lysp_embed" when wired

    def assert_rule(self, rule: str, meta: Optional[Dict[str, Any]] = None) -> str:
        # Future: also push rule form into Lisp image
        return self.fallback.assert_rule(rule, meta)

    def query(self, expression: str) -> Dict[str, Any]:
        out = self.fallback.query(expression)
        out["bridge"] = self.name
        out["backend"] = self.backend
        out["note"] = (
            "LYSP runtime not embedded yet; using RuleSymbolicReasoner. "
            "Swap backend without changing SIOrchestrator."
        )
        return out

    def list_rules(self) -> List[Dict[str, Any]]:
        return self.fallback.list_rules()

    def eval_lisp(self, form: str) -> Dict[str, Any]:
        """Reserved for true Lisp eval."""
        return {
            "ok": False,
            "error": "lysp_not_embedded",
            "form": form,
            "hint": "Phase 2: embed LYSP and implement eval_lisp",
        }
