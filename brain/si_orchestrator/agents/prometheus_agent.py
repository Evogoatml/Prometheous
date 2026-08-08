"""
Prometheus synthetic agent — primary SI persona.

Native perceive/plan/act/reflect sketch using recalled memory + symbolic hints.
No external LLM required for Phase 1.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from ..core.interfaces import Agent, AgentResult, AgentTask


class PrometheusAgent(Agent):
    name = "prometheus"
    version = "1.0.0"
    skills: Sequence[str] = (
        "reason",
        "plan",
        "memory",
        "self",
        "analyze",
        "prometheus",
        "synthetic",
    )

    def run(self, task: AgentTask) -> AgentResult:
        goal = task.goal.strip()
        recalled = task.context.get("recalled") or []
        symbolic = task.context.get("symbolic") or {}
        traces: List[Dict[str, Any]] = []

        intent = self._classify(goal)
        traces.append({"step": "classify", "intent": intent})

        plan = self._plan(goal, intent, recalled, symbolic)
        traces.append({"step": "plan", "steps": plan})

        # Act: synthesize answer from memory + plan (native)
        answer_parts = [
            f"Prometheus (synthetic agent) · intent={intent}",
            f"Goal: {goal}",
        ]
        if recalled:
            answer_parts.append("Memory recall:")
            for r in recalled[:3]:
                answer_parts.append(
                    f"  - [{r.get('score', 0):.2f}] {str(r.get('content', ''))[:160]}"
                )
        else:
            answer_parts.append("Memory recall: (empty — first episodes will seed learning)")

        fired = (symbolic or {}).get("fired") or []
        if fired:
            answer_parts.append("Symbolic rules fired:")
            for f in fired[:3]:
                answer_parts.append(f"  - {f.get('action')}")

        answer_parts.append("Plan:")
        for i, step in enumerate(plan, 1):
            answer_parts.append(f"  {i}. {step}")

        if intent == "self":
            answer_parts.append(
                "Identity: I am Prometheus under the SI Orchestrator — "
                "I own planning/reflection; memory and learning are pluggable backends."
            )

        output = "\n".join(answer_parts)
        traces.append({"step": "synthesize", "chars": len(output)})

        return AgentResult(
            task_id=task.id,
            success=True,
            output=output,
            traces=traces,
        )

    def _classify(self, goal: str) -> str:
        g = goal.lower()
        if any(k in g for k in ("who are you", "yourself", "prometheus", "capabilities")):
            return "self"
        if any(k in g for k in ("remember", "recall", "memory")):
            return "memory"
        if any(k in g for k in ("learn", "improve", "train")):
            return "learning"
        if any(k in g for k in ("analyze", "review", "audit", "explain")):
            return "analyze"
        if any(k in g for k in ("plan", "build", "create", "design")):
            return "create"
        return "generic"

    def _plan(
        self,
        goal: str,
        intent: str,
        recalled: List[Dict[str, Any]],
        symbolic: Dict[str, Any],
    ) -> List[str]:
        steps = [
            "Classify intent (native)",
            "Recall related episodes from MemoryBackend",
            "Apply symbolic rules if any fire",
        ]
        if intent == "self":
            steps += ["Describe identity and registry surface", "Report skills"]
        elif intent == "memory":
            steps += ["Summarize recalled items with provenance", "Store new episode"]
        elif intent == "learning":
            steps += ["Observe outcome", "Run LearningStrategy.improve()"]
        elif intent == "analyze":
            steps += ["Break down goal", "Cite memory evidence", "Conclude"]
        else:
            steps += ["Form answer from context", "Persist episode for future recall"]
        # path hints
        if re.search(r"\.(py|md|json)\b", goal):
            steps.append("Note referenced artifact paths for future tools")
        if recalled:
            steps.append(f"Integrate {len(recalled)} memory hits")
        return steps
