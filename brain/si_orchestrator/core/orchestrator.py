"""
SI Orchestrator — task routing and lifecycle.

Owns: perceive → recall → plan/route → act (agent) → learn → remember.
LLM (if any) is optional and never owns decision authority.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..utils.ids import new_id
from .interfaces import (
    AgentResult,
    AgentTask,
    MemoryRecord,
    RecallQuery,
)
from .registry import Registry

logger = logging.getLogger("si_orchestrator.core")


@dataclass
class CycleResult:
    goal: str
    success: bool
    agent: Optional[str]
    output: Any
    recalled: List[Dict[str, Any]] = field(default_factory=list)
    learning: Dict[str, Any] = field(default_factory=dict)
    traces: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "success": self.success,
            "agent": self.agent,
            "output": self.output,
            "recalled": self.recalled,
            "learning": self.learning,
            "traces": self.traces,
            "error": self.error,
        }


class SIOrchestrator:
    """
    Minimal viable synthetic-intelligence orchestrator.

    Dependency injection: pass a populated Registry (memory, learning,
    symbolic, agents). Implementations swap without changing this class.
    """

    def __init__(
        self,
        registry: Registry,
        *,
        default_memory: str = "default",
        default_learning: str = "default",
        default_symbolic: str = "default",
        default_agent: str = "prometheus",
    ):
        self.registry = registry
        self.default_memory = default_memory
        self.default_learning = default_learning
        self.default_symbolic = default_symbolic
        self.default_agent = default_agent
        self.cycles = 0

    def run(
        self,
        goal: str,
        *,
        agent_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
    ) -> CycleResult:
        self.cycles += 1
        ctx = dict(context or {})
        traces: List[Dict[str, Any]] = []
        t0 = time.time()

        # 1) RECALL
        recalled: List[MemoryRecord] = []
        try:
            mem = self.registry.get_memory(self.default_memory)
            recalled = mem.recall(RecallQuery(text=goal, top_k=top_k))
            traces.append(
                {
                    "step": "recall",
                    "hits": len(recalled),
                    "backend": mem.name,
                }
            )
        except Exception as exc:  # noqa: BLE001
            traces.append({"step": "recall", "error": str(exc)})

        ctx["recalled"] = [r.to_dict() for r in recalled]

        # 2) OPTIONAL symbolic assist
        try:
            sym = self.registry.get_symbolic(self.default_symbolic)
            sym_out = sym.query(goal)
            ctx["symbolic"] = sym_out
            traces.append({"step": "symbolic", "result": sym_out})
        except Exception as exc:  # noqa: BLE001
            traces.append({"step": "symbolic", "error": str(exc)})

        # 3) ROUTE + ACT
        agent_key = agent_name or self._route_agent(goal) or self.default_agent
        task = AgentTask(id=new_id("task"), goal=goal, context=ctx)
        try:
            agent = self.registry.get_agent(agent_key)
            result: AgentResult = agent.run(task)
            traces.append(
                {
                    "step": "act",
                    "agent": agent_key,
                    "success": result.success,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent failure")
            result = AgentResult(task_id=task.id, success=False, error=str(exc))
            traces.append({"step": "act", "error": str(exc)})

        # 4) REMEMBER episode (richer for ranking: goal + success + summary)
        try:
            mem = self.registry.get_memory(self.default_memory)
            out_s = str(result.output)[:500]
            rec = MemoryRecord(
                id=new_id("mem"),
                content=(
                    f"GOAL: {goal}\n"
                    f"AGENT: {agent_key}\n"
                    f"SUCCESS: {result.success}\n"
                    f"OUT: {out_s}"
                ),
                kind="episode",
                tags=[
                    "cycle",
                    agent_key,
                    "success" if result.success else "failed",
                ],
                provenance={
                    "agent": agent_key,
                    "task_id": task.id,
                    "cycle": self.cycles,
                    "success": bool(result.success),
                    "goal": goal[:300],
                },
                created_at=time.time(),
                score=1.0 if result.success else 0.3,
            )
            mem.store(rec)
            traces.append({"step": "store", "id": rec.id})
        except Exception as exc:  # noqa: BLE001
            traces.append({"step": "store", "error": str(exc)})

        # 5) LEARN
        learning_metrics: Dict[str, Any] = {}
        try:
            learn = self.registry.get_learning(self.default_learning)
            learn.observe(
                {
                    "goal": goal,
                    "success": result.success,
                    "agent": agent_key,
                    "output": result.output,
                    "error": result.error,
                    "duration_s": time.time() - t0,
                }
            )
            learning_metrics = learn.improve()
            traces.append({"step": "learn", "metrics": learning_metrics})
        except Exception as exc:  # noqa: BLE001
            traces.append({"step": "learn", "error": str(exc)})

        return CycleResult(
            goal=goal,
            success=bool(result.success),
            agent=agent_key,
            output=result.output,
            recalled=[r.to_dict() for r in recalled],
            learning=learning_metrics,
            traces=traces,
            error=result.error,
        )

    def _route_agent(self, goal: str) -> Optional[str]:
        """Skill match + light bias away from agents that fail often in learning buffer."""
        g = goal.lower()
        try:
            from ..learning.tuning_state import get_active_tuning

            tp = get_active_tuning()
            tool_boost = tp.tool_cue_boost
            w_skill = tp.skill_match_weight
            w_name = tp.name_match_weight
            w_fail = tp.fail_bias_weight
        except Exception:
            tool_boost, w_skill, w_name, w_fail = 3.0, 1.0, 2.0, 0.35

        # Prefer tools when the goal is clearly file/search oriented
        # (not when user asks about the agent's own "tools/capabilities")
        meta_self = any(
            x in g
            for x in (
                "who are you",
                "your capabilities",
                "your tools",
                "as a synthetic",
                "what are you",
            )
        )
        tool_cues = (
            "search for", "find file", "grep", "list files", "read file",
            "open ", "cat ", "where is", "show file", "ls ",
        )
        if (
            not meta_self
            and any(c in g for c in tool_cues)
            and "tools" in self.registry.agents
            and tool_boost >= 2.0
        ):
            return "tools"

        fail_bias: Dict[str, int] = {}
        try:
            learn = self.registry.get_learning(self.default_learning)
            if hasattr(learn, "buffer"):
                for exp in list(getattr(learn, "buffer"))[-30:]:
                    if not exp.get("success"):
                        a = str(exp.get("agent") or "")
                        if a:
                            fail_bias[a] = fail_bias.get(a, 0) + 1
        except Exception:  # noqa: BLE001
            pass

        best = None
        best_score = -1.0
        for name, agent in self.registry.agents.items():
            score = 0.0
            for skill in agent.skills:
                if skill.lower() in g:
                    score += w_skill
            if name.lower() in g:
                score += w_name
            if name == "tools" and any(c in g for c in tool_cues):
                score += tool_boost
            score -= w_fail * fail_bias.get(name, 0)
            if score > best_score:
                best_score = score
                best = name
        return best if best_score > 0 else None

    def status(self) -> Dict[str, Any]:
        return {
            "cycles": self.cycles,
            "registry": self.registry.summary(),
        }
