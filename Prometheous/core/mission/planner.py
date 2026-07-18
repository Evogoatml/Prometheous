"""
Mission planner — turn a free-text task into an ordered executable plan.

Supports fleets of many agents (default cap 100), not just one:
  plan → code (shared templates + fleet modules) → deploy N → execute N (parallel)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from core.mission.fleet import FleetMember, build_fleet, fleet_summary, max_agents
from core.mission.frameworks import FRAMEWORKS, mentioned_frameworks


@dataclass
class PlanStep:
    id: int
    kind: str  # research | code | deploy | deploy_fleet | execute | execute_fleet | tool | synthesize | specialist
    title: str
    why: str
    agent: Optional[str] = None
    write_path: Optional[str] = None
    code_spec: Optional[str] = None
    deploy_name: Optional[str] = None
    deploy_module: Optional[str] = None
    payload_hint: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and v != {}}


@dataclass
class MissionPlan:
    goal: str
    summary: str
    steps: List[PlanStep]
    agents_needed: List[str]
    code_artifacts: List[str]
    success_criteria: List[str]
    fleet: List[Dict[str, Any]] = field(default_factory=list)
    fleet_size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "summary": self.summary,
            "agents_needed": self.agents_needed,
            "code_artifacts": self.code_artifacts,
            "success_criteria": self.success_criteria,
            "fleet_size": self.fleet_size,
            "fleet": self.fleet,
            "steps": [s.to_dict() for s in self.steps],
        }

    def markdown(self) -> str:
        lines = [
            "# Mission plan",
            "",
            f"**Goal:** {self.goal}",
            "",
            f"**Summary:** {self.summary}",
            "",
            f"**Fleet size:** {self.fleet_size} (cap {max_agents()})",
            "",
            "## Agents to deploy / use",
            "",
        ]
        # Don't dump 100 lines — summarize large fleets
        if self.fleet_size <= 12:
            for a in self.agents_needed:
                lines.append(f"- `{a}`")
        else:
            lines.append(f"- {fleet_summary([FleetMember(**m) if isinstance(m, dict) else m for m in self._fleet_objs()])}")
            lines.append(f"- names: `{self.agents_needed[0]}` … `{self.agents_needed[-1]}`")
            # role breakdown
            roles: Dict[str, int] = {}
            for m in self.fleet:
                roles[m.get("role", "worker")] = roles.get(m.get("role", "worker"), 0) + 1
            for role, n in roles.items():
                lines.append(f"- role `{role}` × {n}")
        lines += ["", "## Steps", ""]
        for s in self.steps:
            lines.append(f"### {s.id}. [{s.kind}] {s.title}")
            lines.append(f"- **Why:** {s.why}")
            if s.agent:
                lines.append(f"- **Agent:** `{s.agent}`")
            if s.write_path:
                lines.append(f"- **Write:** `{s.write_path}`")
            if s.code_spec:
                lines.append(f"- **Spec:** {s.code_spec[:300]}")
            if s.deploy_name:
                lines.append(f"- **Deploy as:** `{s.deploy_name}`")
            if s.args.get("fleet_size"):
                lines.append(f"- **Fleet:** {s.args['fleet_size']} agents")
            lines.append("")
        lines += ["## Success criteria", ""]
        for c in self.success_criteria:
            lines.append(f"- [ ] {c}")
        lines.append("")
        return "\n".join(lines)

    def _fleet_objs(self) -> List[Any]:
        return self.fleet


def plan_mission(goal: str) -> MissionPlan:
    """Build an executable plan from a natural-language task (multi-agent capable)."""
    goal = (goal or "").strip()
    g = goal.lower()
    steps: List[PlanStep] = []
    agents: List[str] = []
    code_artifacts: List[str] = []
    n = 1

    needs_research = bool(
        re.search(
            r"\b(?:research|find|look\s*up|how\s+to|plan|strategy|launch|market|"
            r"compare|best|learn|investigate)\b",
            g,
        )
    )
    needs_code = bool(
        re.search(
            r"\b(?:code|script|python|implement|build|write|bot|agent|automate|"
            r"deploy|module|function|create|swarm|fleet)\b",
            g,
        )
        or re.search(r"\.(?:py|sh|js)\b", g)
    )
    needs_bot = bool(
        re.search(
            r"\b(?:bot|agent|worker|daemon|service|deploy\s+agent|spawn|swarm|fleet)\b",
            g,
        )
    )
    needs_ads = bool(
        re.search(r"\b(?:shopify|meta\s+ads?|facebook\s+ads?|ad\s*campaign)\b", g)
    )
    needs_growth = bool(
        re.search(r"\b(?:grow|github|huggingface|self[- ]?improv)\b", g)
    )
    needs_scan = bool(re.search(r"\b(?:scan|nmap|port\s*scan)\b", g))

    path_m = re.search(
        r"(?:under|to|into|as|at|in)\s+[`\"']?([\w./-]+\.[\w]+)[`\"']?",
        goal,
        re.I,
    )
    explicit_path = path_m.group(1) if path_m else None

    fleet = build_fleet(goal)
    fleet_dicts = [m.to_dict() for m in fleet]
    fleet_size = len(fleet)
    frameworks = mentioned_frameworks(goal)
    # Default stack always available for multi-bot / deploy missions
    use_frameworks = bool(frameworks) or needs_bot or fleet_size > 1 or bool(
        re.search(r"\b(?:crew|swarm|superagi|agentgpt|agent\s*k)\b", g)
    )
    if use_frameworks and not frameworks:
        frameworks = list(FRAMEWORKS)

    steps.append(
        PlanStep(
            id=n,
            kind="synthesize",
            title="Record mission brief and success criteria",
            why="Make the plan inspectable before action",
            agent="mission",
            args={"fleet_size": fleet_size, "frameworks": frameworks},
        )
    )
    n += 1

    # Framework stack: SuperAGI → CrewAI → AgentGPT → AgentK → Swarm AI
    if use_frameworks:
        steps.append(
            PlanStep(
                id=n,
                kind="framework_stack",
                title=(
                    f"Run framework stack ({' + '.join(frameworks)}) "
                    f"with fleet×{fleet_size}"
                ),
                why=(
                    "SuperAGI plans subtasks, CrewAI coordinates, AgentGPT researches, "
                    "AgentK runs skills, Swarm AI parallel-executes N workers"
                ),
                agent="mission",
                args={
                    "frameworks": frameworks,
                    "fleet_size": max(fleet_size, 1),
                    "fleet": fleet_dicts,
                },
            )
        )
        for fw in frameworks:
            if fw not in agents:
                agents.append(fw)
        n += 1

    if needs_research and "agentgpt" not in frameworks:
        steps.append(
            PlanStep(
                id=n,
                kind="research",
                title="Research the task domain",
                why="Gather external facts before coding or deploying",
                agent="web_search",
                payload_hint=goal,
            )
        )
        agents.append("web_search")
        n += 1

    if needs_growth:
        steps.append(
            PlanStep(
                id=n,
                kind="specialist",
                title="Grow capability from GitHub/HuggingFace",
                why="Pull external patterns into a skill",
                agent="growth",
                payload_hint=goal,
            )
        )
        agents.append("growth")
        n += 1

    if needs_ads:
        steps.append(
            PlanStep(
                id=n,
                kind="specialist",
                title="Run ads / growth campaign pipeline",
                why="Domain specialist owns Shopify/Meta packaging",
                agent="shopify_ads",
                payload_hint=goal,
            )
        )
        agents.append("shopify_ads")
        n += 1

    if needs_scan:
        steps.append(
            PlanStep(
                id=n,
                kind="specialist",
                title="Run scanner agent",
                why="Security/surface scan requested",
                agent="scanner",
                payload_hint=goal,
            )
        )
        agents.append("scanner")
        n += 1

    # ── Fleet: code + deploy + execute many (custom workers, in addition to frameworks) ──
    # Skip custom fleet codegen when user only asked for framework stack by name
    frameworks_only = bool(mentioned_frameworks(goal)) and not re.search(
        r"\b(?:custom|codegen|write\s+code|script)\b", g
    )
    if (needs_code or needs_bot or fleet_size >= 1) and not frameworks_only:
        # Shared worker template (one module, parameterized by shard)
        base = fleet[0].base if fleet else "mission_worker"
        worker_path = (
            explicit_path
            if explicit_path and fleet_size == 1
            else f"data/missions/{{mission_id}}/fleet_worker.py"
        )
        agent_path = f"data/missions/{{mission_id}}/agents/fleet_agent.py"

        steps.append(
            PlanStep(
                id=n,
                kind="code",
                title=f"Write shared fleet worker (`{base}`, ×{fleet_size})",
                why="One worker template runs for every fleet member (shard-aware)",
                agent="mission",
                write_path=worker_path,
                code_spec=f"Shard-aware worker for fleet of {fleet_size}. Goal: {goal[:200]}",
                args={
                    "role": "fleet_worker",
                    "bot_name": base,
                    "fleet": fleet_dicts,
                    "fleet_size": fleet_size,
                },
            )
        )
        code_artifacts.append(worker_path)
        n += 1

        if needs_bot or fleet_size >= 1 or re.search(r"\b(?:deploy|agent|bot|swarm|fleet)\b", g):
            steps.append(
                PlanStep(
                    id=n,
                    kind="code",
                    title=f"Write fleet agent factory (deploys {fleet_size} agents)",
                    why="Single module registers N agent instances on the orchestrator",
                    agent="mission",
                    write_path=agent_path,
                    code_spec=f"Fleet agent factory for {fleet_size} members",
                    args={
                        "role": "fleet_agent",
                        "bot_name": base,
                        "fleet": fleet_dicts,
                        "fleet_size": fleet_size,
                    },
                    deploy_name=base,
                )
            )
            code_artifacts.append(agent_path)
            n += 1

            steps.append(
                PlanStep(
                    id=n,
                    kind="deploy_fleet",
                    title=f"Deploy fleet of {fleet_size} agents in parallel",
                    why="Register every fleet member so they can run concurrently",
                    agent="mission",
                    deploy_module=agent_path,
                    args={
                        "fleet": fleet_dicts,
                        "fleet_size": fleet_size,
                        "module": agent_path,
                    },
                )
            )
            for m in fleet:
                agents.append(m.name)
            n += 1

            steps.append(
                PlanStep(
                    id=n,
                    kind="execute_fleet",
                    title=f"Execute all {fleet_size} agents (parallel)",
                    why="Swarm runs together — not one-at-a-time serial bottleneck",
                    agent="mission",
                    payload_hint=goal,
                    args={
                        "fleet": fleet_dicts,
                        "fleet_size": fleet_size,
                    },
                )
            )
            n += 1
        elif fleet_size == 1:
            steps.append(
                PlanStep(
                    id=n,
                    kind="execute",
                    title="Run the generated script",
                    why="Verify the written code works",
                    agent="mission",
                    write_path=worker_path,
                    args={"run_script": True, "bot_name": base},
                )
            )
            n += 1

    if len(steps) <= 1:
        steps.append(
            PlanStep(
                id=n,
                kind="execute",
                title="Execute via autonomous task agent",
                why="General executor handles research/files/tools",
                agent="task",
                payload_hint=goal,
            )
        )
        agents.append("task")
        n += 1

    steps.append(
        PlanStep(
            id=n,
            kind="synthesize",
            title="Collect results and write mission report",
            why="User gets a clear record of plan, code, deploys, and outcomes",
            agent="mission",
            args={"fleet_size": fleet_size},
        )
    )

    seen = set()
    agents_needed = []
    for a in agents:
        if a not in seen:
            seen.add(a)
            agents_needed.append(a)
    if "mission" not in agents_needed:
        agents_needed.insert(0, "mission")

    criteria = [
        "Plan written under data/missions/",
        f"Fleet of {fleet_size} planned (cap {max_agents()})",
        "Required code files exist and are non-empty",
    ]
    if needs_bot or fleet_size:
        criteria.append(f"All {fleet_size} agents registered on orchestrator")
        criteria.append(f"Fleet executed ({fleet_size} workers)")
    criteria.append("Mission report produced")

    fw_note = f" frameworks=[{', '.join(frameworks)}]" if frameworks else ""
    summary = (
        f"For «{goal[:100]}»: plan →{fw_note} → deploy {fleet_summary(fleet)} "
        f"→ execute in parallel. Cap={max_agents()}."
    )

    return MissionPlan(
        goal=goal,
        summary=summary,
        steps=steps,
        agents_needed=agents_needed,
        code_artifacts=code_artifacts,
        success_criteria=criteria,
        fleet=fleet_dicts,
        fleet_size=fleet_size,
    )
