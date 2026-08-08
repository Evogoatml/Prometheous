"""
Fleet sizing and role decomposition.

A mission is not limited to one agent. Goals can mean:
  - "deploy 100 bots"
  - "swarm of 20 researchers"
  - "research bot, coder bot, and notifier bot"
  - multi-role teams inferred from the task
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


def max_agents() -> int:
    try:
        return max(1, int(os.getenv("PROM_MISSION_MAX_AGENTS", "100")))
    except ValueError:
        return 100


def parallel_workers(n: int) -> int:
    """How many agents to run concurrently."""
    try:
        cap = int(os.getenv("PROM_SWARM_MAX_PARALLEL", "16"))
    except ValueError:
        cap = 16
    cap = max(1, min(cap, 64))
    return max(1, min(n, cap))


@dataclass
class FleetMember:
    name: str
    role: str  # researcher | coder | reviewer | worker | scout | ...
    specialty: str
    shard: int = 0
    fleet_size: int = 1
    base: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Word counts for casual language
_WORD_COUNTS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "dozen": 12,
    "twenty": 20,
    "thirty": 30,
    "fifty": 50,
    "hundred": 100,
}


def infer_count(goal: str) -> int:
    """How many agents/bots the user asked for (capped)."""
    g = (goal or "").lower()
    cap = max_agents()

    # "100 agents", "20 checklist bots", "deploy 12 recon workers"
    m = re.search(
        r"\b(\d{1,4})\s+(?:[\w-]+\s+){0,4}(?:agents?|bots?|workers?|nodes?|instances?)\b",
        g,
    )
    if m:
        return max(1, min(int(m.group(1)), cap))

    # "swarm of 40", "fleet of 25"
    m = re.search(r"\b(?:swarm|fleet|army|team)\s+of\s+(\d{1,4})\b", g)
    if m:
        return max(1, min(int(m.group(1)), cap))

    # "a hundred bots", "fifty checklist agents"
    m = re.search(
        r"\b(a\s+)?(hundred|fifty|thirty|twenty|dozen|ten|five|three|two|one)\s+"
        r"(?:[\w-]+\s+){0,4}(?:agents?|bots?|workers?)\b",
        g,
    )
    if m:
        word = m.group(2)
        return max(1, min(_WORD_COUNTS.get(word, 1), cap))

    # "as many as you can" / "max agents"
    if re.search(r"\b(?:as many as|max(?:imum)?|all the|full swarm|saturate)\b", g):
        return cap

    return 0  # unknown — let role decomposition decide


def _named_bots(goal: str) -> List[str]:
    """Extract explicit multi-bot names: research bot, scraper agent, ..."""
    names: List[str] = []
    for m in re.finditer(
        r"\b([\w-]+)\s+(?:bot|agent|worker)s?\b",
        goal,
        re.I,
    ):
        raw = m.group(1).lower()
        if raw in {
            "a",
            "an",
            "the",
            "my",
            "our",
            "new",
            "this",
            "that",
            "each",
            "every",
            "deploy",
            "build",
            "create",
            "make",
            "spawn",
            "run",
            "and",
            "or",
            "with",
            "for",
            "mission",
            "swarm",
            "fleet",
        }:
            continue
        if raw.isdigit():
            continue
        clean = re.sub(r"[^a-z0-9_]+", "_", raw)[:24].strip("_")
        if clean and clean not in names:
            names.append(clean)
    return names


def _roles_from_goal(goal: str) -> List[Tuple[str, str, str]]:
    """
    Multi-role team inferred from task language.
    Returns list of (base_name, role, specialty).
    """
    g = goal.lower()
    roles: List[Tuple[str, str, str]] = []

    def add(name: str, role: str, specialty: str) -> None:
        if not any(r[0] == name for r in roles):
            roles.append((name, role, specialty))

    if re.search(r"\b(?:research|investigat|look\s*up|survey)\b", g):
        add("researcher", "researcher", "gather evidence and sources")
    if re.search(r"\b(?:code|script|implement|build|python|engineer)\b", g):
        add("coder", "coder", "write and run code")
    if re.search(r"\b(?:review|audit|qa|test|verify)\b", g):
        add("reviewer", "reviewer", "critique and verify")
    if re.search(r"\b(?:scrape|crawl|fetch|monitor)\b", g):
        add("scout", "worker", "fetch/monitor external data")
    if re.search(r"\b(?:notif|alert|report|summar)\b", g):
        add("reporter", "worker", "summarize and notify")
    if re.search(r"\b(?:price|pricing|market)\b", g):
        add("pricer", "worker", "pricing / market signals")
    if re.search(r"\b(?:launch|checklist|store|shop)\b", g):
        add("launcher", "worker", "launch checklist execution")
    if re.search(r"\b(?:ads?|campaign|shopify|meta)\b", g):
        add("ads_runner", "worker", "campaign packaging")

    return roles


def build_fleet(goal: str) -> List[FleetMember]:
    """
    Decide the full set of agents to code/deploy/run for this goal.

    Not capped at 1 — up to PROM_MISSION_MAX_AGENTS (default 100).
    """
    g = (goal or "").strip()
    count = infer_count(g)
    named = _named_bots(g)
    roles = _roles_from_goal(g)
    cap = max_agents()

    members: List[FleetMember] = []

    # 1) Explicit multi-named bots ("research bot and scraper bot")
    if len(named) >= 2 and count <= 1:
        for i, name in enumerate(named):
            role = "worker"
            if "research" in name:
                role = "researcher"
            elif "code" in name or "dev" in name:
                role = "coder"
            elif "review" in name or "audit" in name:
                role = "reviewer"
            members.append(
                FleetMember(
                    name=name,
                    role=role,
                    specialty=f"handles {name} work for: {g[:80]}",
                    shard=i,
                    fleet_size=len(named),
                    base=name,
                )
            )
        return members[:cap]

    # 2) Explicit count (N agents/bots) — homogeneous or multi-role shards
    if count >= 2:
        if roles:
            # round-robin roles across N workers
            for i in range(count):
                base, role, specialty = roles[i % len(roles)]
                name = f"{base}_{i:03d}" if count > len(roles) else (
                    base if count == len(roles) and i < len(roles) else f"{base}_{i:03d}"
                )
                # always unique names for N>roles
                if count > len(roles):
                    name = f"{base}_{i:03d}"
                else:
                    name = f"{base}_{i:03d}" if count > 1 else base
                members.append(
                    FleetMember(
                        name=name,
                        role=role,
                        specialty=specialty,
                        shard=i,
                        fleet_size=count,
                        base=base,
                    )
                )
        else:
            base = named[0] if named else _default_base(g)
            for i in range(count):
                name = f"{base}_{i:03d}" if count > 1 else base
                members.append(
                    FleetMember(
                        name=name,
                        role="worker",
                        specialty=f"fleet worker {i+1}/{count} for: {g[:80]}",
                        shard=i,
                        fleet_size=count,
                        base=base,
                    )
                )
        return members[:cap]

    # 3) Multi-role team without explicit count (heterogeneous 1 each)
    if len(roles) >= 2:
        for i, (base, role, specialty) in enumerate(roles):
            members.append(
                FleetMember(
                    name=base,
                    role=role,
                    specialty=specialty,
                    shard=i,
                    fleet_size=len(roles),
                    base=base,
                )
            )
        return members[:cap]

    # 4) Single named or default bot (still a fleet of 1 — not a hard ceiling)
    if named:
        name = named[0]
        members.append(
            FleetMember(
                name=name,
                role="worker",
                specialty=f"primary bot for: {g[:100]}",
                shard=0,
                fleet_size=1,
                base=name,
            )
        )
        return members

    if roles:
        base, role, specialty = roles[0]
        members.append(
            FleetMember(
                name=base,
                role=role,
                specialty=specialty,
                shard=0,
                fleet_size=1,
                base=base,
            )
        )
        return members

    base = _default_base(g)
    members.append(
        FleetMember(
            name=base,
            role="worker",
            specialty=f"mission worker for: {g[:100]}",
            shard=0,
            fleet_size=1,
            base=base,
        )
    )
    return members


def _default_base(goal: str) -> str:
    g = goal.lower()
    for key, name in (
        ("monitor", "monitor"),
        ("scraper", "scraper"),
        ("scrape", "scraper"),
        ("research", "researcher"),
        ("report", "reporter"),
        ("price", "pricer"),
        ("launch", "launcher"),
        ("checklist", "checklist"),
        ("hello", "hello"),
        ("notify", "notifier"),
        ("telegram", "telegram_worker"),
    ):
        if key in g:
            return name
    return "mission_worker"


def fleet_summary(members: List[FleetMember]) -> str:
    if not members:
        return "no agents"
    if len(members) == 1:
        return f"1 agent (`{members[0].name}`)"
    bases: Dict[str, int] = {}
    for m in members:
        bases[m.base or m.role] = bases.get(m.base or m.role, 0) + 1
    parts = [f"{n}× {b}" for b, n in bases.items()]
    return f"{len(members)} agents ({', '.join(parts)})"
