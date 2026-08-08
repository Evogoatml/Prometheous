"""Training curriculum — graded goals with expected outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Scenario:
    id: str
    goal: str
    # soft expectations used for scoring
    expect_agent: Optional[str] = None  # prometheus | tools | echo
    expect_success: bool = True
    # for tools: require at least N hits or a path substring
    min_tool_hits: int = 0
    path_contains: Optional[str] = None
    # for prometheus: output should mention one of these (case-insensitive)
    output_contains: List[str] = field(default_factory=list)
    weight: float = 1.0
    tags: List[str] = field(default_factory=list)


def default_curriculum() -> List[Scenario]:
    """Core scenarios for Prometheous SI — no full convo dump."""
    return [
        Scenario(
            id="self_id",
            goal="Who are you?",
            expect_agent="prometheus",
            output_contains=["prometheus", "identity", "agent"],
            weight=1.0,
            tags=["identity"],
        ),
        Scenario(
            id="self_capabilities",
            goal="What are your capabilities as a synthetic agent?",
            expect_agent="prometheus",
            output_contains=["plan", "memory", "skill"],
            weight=1.0,
            tags=["identity"],
        ),
        Scenario(
            id="search_hybrid",
            goal="search for HybridMemoryBackend",
            expect_agent="tools",
            min_tool_hits=1,
            path_contains="hybrid",
            weight=1.5,
            tags=["tools", "search"],
        ),
        Scenario(
            id="search_orchestrator",
            goal="search for SIOrchestrator",
            expect_agent="tools",
            min_tool_hits=1,
            path_contains="orchestrator",
            weight=1.5,
            tags=["tools", "search"],
        ),
        Scenario(
            id="search_tuning",
            goal="find file tuning_state",
            expect_agent="tools",
            min_tool_hits=0,  # may miss until trainer files exist — still routes tools
            weight=1.0,
            tags=["tools"],
        ),
        Scenario(
            id="memory_remember",
            goal="remember that modular hybrid memory is the default brain fabric",
            expect_agent="prometheus",
            expect_success=True,
            output_contains=["memory", "plan"],
            weight=1.2,
            tags=["memory"],
        ),
        Scenario(
            id="memory_recall",
            goal="recall modular hybrid memory",
            expect_agent="prometheus",
            output_contains=["memory", "recall", "hybrid"],
            weight=1.5,
            tags=["memory", "recall"],
        ),
        Scenario(
            id="analyze_si",
            goal="analyze the SI orchestrator design briefly",
            expect_agent="prometheus",
            output_contains=["plan", "intent"],
            weight=1.0,
            tags=["reason"],
        ),
        Scenario(
            id="list_si_dir",
            goal="list files in brain/si_orchestrator",
            expect_agent="tools",
            weight=1.0,
            tags=["tools", "list"],
        ),
        Scenario(
            id="read_readme",
            goal="read file README.md in si_orchestrator",
            expect_agent="tools",
            weight=1.2,
            tags=["tools", "read"],
        ),
    ]


def eval_scenario(scenario: Scenario, cycle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score one run in [0, 1] with component breakdown.
    cycle = CycleResult.to_dict()
    """
    parts: Dict[str, float] = {}
    success = bool(cycle.get("success"))
    agent = cycle.get("agent")
    output = cycle.get("output")
    out_s = str(output).lower() if output is not None else ""

    # success bit
    if scenario.expect_success:
        parts["success"] = 1.0 if success else 0.0
    else:
        parts["success"] = 1.0

    # agent routing
    if scenario.expect_agent:
        parts["agent"] = 1.0 if agent == scenario.expect_agent else 0.0
    else:
        parts["agent"] = 1.0

    # tools hits
    if scenario.min_tool_hits or scenario.path_contains:
        hits = []
        if isinstance(output, dict):
            hits = output.get("hits") or []
            if output.get("path"):
                hits = hits or [{"path": output.get("path")}]
            if output.get("entries") is not None:
                # list success
                parts["tool_payload"] = 1.0 if output.get("entries") is not None else 0.0
            if output.get("content") is not None:
                parts["tool_payload"] = 1.0
        hit_score = 1.0 if len(hits) >= scenario.min_tool_hits else (
            0.5 if hits else 0.0
        )
        parts["tool_hits"] = hit_score
        if scenario.path_contains:
            blob = json_dumps_lower(output)
            parts["path"] = 1.0 if scenario.path_contains.lower() in blob else 0.0

    # output keywords
    if scenario.output_contains:
        ok = sum(1 for k in scenario.output_contains if k.lower() in out_s)
        parts["keywords"] = ok / max(len(scenario.output_contains), 1)

    # weighted mean of parts
    if not parts:
        score = 1.0 if success else 0.0
    else:
        score = sum(parts.values()) / len(parts)

    return {
        "scenario_id": scenario.id,
        "score": score,
        "weight": scenario.weight,
        "weighted_score": score * scenario.weight,
        "parts": parts,
        "agent": agent,
        "success": success,
    }


def json_dumps_lower(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj, default=str).lower()
    except Exception:
        return str(obj).lower()
