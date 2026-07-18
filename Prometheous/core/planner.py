"""
Goal planner — turn a free-form goal into an executable plan.

A plan is a list of steps, each of which is a Decision-like intent that
the existing orchestrator can dispatch. The planner uses the LLM to
decompose the goal; if the LLM is unavailable, it falls back to a
small set of keyword rules.

Public surface:
    from core.planner import plan, Plan, PlanStep

    p = plan("scan 127.0.0.1 and summarize")
    for step in p.steps:
        print(step.intent, step.agent, step.payload)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single executable step. Mirrors core.decision.Decision fields."""
    intent: str           # e.g. "dispatch", "respond", "create_skill", "run_skill"
    agent: Optional[str]  # agent name to dispatch to
    payload: Dict[str, Any] = field(default_factory=dict)
    description: str = ""  # human-readable (for CLI display)
    depends_on: List[int] = field(default_factory=list)  # indices of prereq steps


@dataclass
class Plan:
    goal: str
    steps: List[PlanStep]
    source: str = "rule"   # "llm" | "rule"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "source": self.source,
            "notes": self.notes,
            "steps": [
                {
                    "i": i,
                    "intent": s.intent,
                    "agent": s.agent,
                    "description": s.description,
                    "depends_on": s.depends_on,
                    "payload": s.payload,
                }
                for i, s in enumerate(self.steps)
            ],
        }


_DECOMPOSE_PROMPT = """You are a planner for a multi-agent system with these agents: {agents}.
Given a user goal, return a JSON plan: an array of steps, each with:
  intent: "dispatch" | "respond" | "run_skill"
  agent: one of the available agent names (for dispatch), or null (for respond)
  description: short human-readable summary
  payload: object with parameters for that agent (e.g. {{"target": "127.0.0.1", "ports": [22,80,443]}})

Rules:
- Output ONLY valid JSON, no prose.
- Keep the plan minimal — usually 1-4 steps.
- If the goal is just chat, return one step with intent=respond and agent=null.
- If you don't know which agent, use "scanner" for network tasks and "web_search" for info lookups.

Goal: {goal}
JSON:"""


def _available_agents() -> List[str]:
    """Return the list of agents currently registered with the orchestrator."""
    try:
        from core.orchestrator import orchestrator
        return orchestrator.list_agents()
    except Exception:
        return []


def _llm_decompose(goal: str) -> Optional[Plan]:
    """Use the LLM to decompose. Returns None on any failure."""
    try:
        from llm.client import llm
        if not llm.enabled():
            return None
    except Exception:
        return None
    agents = _available_agents() or ["scanner", "web_search", "paradox", "knowledge", "matrix", "cogno", "telegram"]
    prompt = _DECOMPOSE_PROMPT.format(agents=", ".join(agents), goal=goal)
    raw = llm.respond({"intent": "plan", "agents": agents, "goal": goal}, prompt)
    if not raw:
        return None
    # Extract JSON robustly — LLM sometimes wraps in ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", raw)
    candidate = m.group(1) if m else raw
    # find the first '[' and last ']' to be safe
    if "[" in candidate:
        s = candidate.index("[")
        e = candidate.rfind("]") + 1
        candidate = candidate[s:e]
    try:
        steps_raw = json.loads(candidate)
    except json.JSONDecodeError as e:
        logger.warning("planner: LLM JSON parse failed: %s; raw=%r", e, raw[:200])
        return None
    if not isinstance(steps_raw, list):
        return None
    steps: List[PlanStep] = []
    for s in steps_raw:
        if not isinstance(s, dict):
            continue
        steps.append(PlanStep(
            intent=str(s.get("intent") or "respond"),
            agent=s.get("agent"),
            payload=dict(s.get("payload") or {}),
            description=str(s.get("description") or ""),
            depends_on=list(s.get("depends_on") or []),
        ))
    if not steps:
        return None
    return Plan(goal=goal, steps=steps, source="llm", notes="")


_KEYWORD_RULES: List[tuple] = [
    # (regex on goal, intent, agent, description_template, payload_extractor)
    (re.compile(r"\b(scan|port[- ]?scan|nmap)\b.*\b([\w.\-]+)\b", re.I),
     "dispatch", "scanner",
     "Run port scan on {target}",
     lambda m: {"target": m.group(2), "ports": [22, 80, 443, 8080, 3306, 5432, 6379]}),
    (re.compile(r"\b(search|look up|find out|what is|who is|when did)\b", re.I),
     "dispatch", "web_search",
     "Search the web for: {goal}",
     lambda m: {"query": m.string}),
    (re.compile(r"\b(summari[sz]e|report|analy[sz]e|review)\b", re.I),
     "respond", None,
     "Summarize findings: {goal}",
     lambda m: {"prompt": m.string}),
    (re.compile(r"\b(list agents|what agents|who can)\b", re.I),
     "respond", None,
     "List available agents",
     lambda m: {"prompt": "list available agents"}),
]


def _rule_decompose(goal: str) -> Plan:
    """Cheap keyword-based fallback when LLM is unavailable."""
    steps: List[PlanStep] = []
    used = False
    for rx, intent, agent, desc_tmpl, payload_fn in _KEYWORD_RULES:
        m = rx.search(goal)
        if not m:
            continue
        steps.append(PlanStep(
            intent=intent,
            agent=agent,
            payload=payload_fn(m),
            description=desc_tmpl.format(target=m.group(2) if m.lastindex and m.lastindex >= 2 else goal,
                                          goal=goal),
        ))
        used = True
        break  # first match wins
    if not steps:
        steps.append(PlanStep(
            intent="respond",
            agent=None,
            payload={"prompt": goal},
            description="Reply: " + goal,
        ))
    return Plan(goal=goal, steps=steps, source="rule",
                notes="" if used else "no keyword matched, single respond step")


def plan(goal: str) -> Plan:
    """Decompose a goal into a Plan. Tries LLM first, then rules."""
    if not goal or not goal.strip():
        return Plan(goal=goal or "", steps=[
            PlanStep(intent="respond", agent=None, payload={"prompt": "(empty goal)"},
                     description="No goal provided")
        ], source="rule", notes="empty goal")
    p = _llm_decompose(goal)
    if p is not None:
        logger.info("planner: LLM produced %d steps for goal=%r", len(p.steps), goal[:60])
        return p
    p = _rule_decompose(goal)
    logger.info("planner: rule-based plan with %d steps for goal=%r", len(p.steps), goal[:60])
    return p
