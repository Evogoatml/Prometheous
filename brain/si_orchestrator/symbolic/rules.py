"""
Lightweight symbolic reasoner (Python rules).

Phase 1 stand-in for LYSP / Lisp bridge. Same SymbolicReasoner interface.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from ..core.interfaces import SymbolicReasoner
from ..utils.ids import new_id


class RuleSymbolicReasoner(SymbolicReasoner):
    name = "rules"
    version = "1.0.0"

    def __init__(self) -> None:
        self.rules: Dict[str, Dict[str, Any]] = {}
        # seed useful identity / SI rules
        self.assert_rule(
            "IF goal CONTAINS self OR who are you THEN prefer agent prometheus",
            {"tag": "routing"},
        )
        self.assert_rule(
            "IF goal CONTAINS remember OR recall OR memory THEN emphasize memory.recall",
            {"tag": "memory"},
        )
        self.assert_rule(
            "IF goal CONTAINS learn OR improve THEN run learning.improve",
            {"tag": "learning"},
        )

    def assert_rule(self, rule: str, meta: Optional[Dict[str, Any]] = None) -> str:
        rid = new_id("rule")
        self.rules[rid] = {
            "id": rid,
            "rule": rule,
            "meta": meta or {},
            "created_at": time.time(),
        }
        return rid

    def query(self, expression: str) -> Dict[str, Any]:
        expr = expression.lower()
        fired: List[Dict[str, Any]] = []
        for rule in self.rules.values():
            text = rule["rule"]
            # very small pattern: IF ... CONTAINS x ...
            m = re.search(r"contains\s+(.+?)\s+then\s+(.+)$", text, re.I)
            if not m:
                continue
            cond = m.group(1).strip()
            action = m.group(2).strip()
            # support OR in condition
            parts = [p.strip() for p in re.split(r"\s+or\s+", cond, flags=re.I)]
            if any(p.lower() in expr for p in parts if p):
                fired.append({"rule_id": rule["id"], "action": action, "rule": text})
        return {
            "expression": expression,
            "fired": fired,
            "count": len(fired),
            "engine": self.name,
        }

    def list_rules(self) -> List[Dict[str, Any]]:
        return list(self.rules.values())
