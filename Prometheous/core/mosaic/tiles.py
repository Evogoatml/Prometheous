"""
Capability tiles — atomic polymorphic units of the mosaic.

Each tile:
  - matches goals via patterns
  - binds a cognitive role (from cognitive_config.yaml)
  - executes via a real agent or in-process tool path
  - can adapt (retry alternate agent / degrade gracefully)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple

from core.mosaic.blackboard import Blackboard


@dataclass
class TileSpec:
    name: str
    role: str  # cognitive context field: researcher | coder | reviewer | ...
    specialty: str
    patterns: List[str]
    agent: Optional[str] = None  # orchestrator agent name
    priority: int = 50  # lower = earlier
    requires_research: bool = False
    always_for_complex: bool = False
    executor: Optional[str] = None  # special: "task_write" | "synthesize" | "mcp"

    def compiled(self) -> List[Pattern]:
        return [re.compile(p, re.I) for p in self.patterns]

    def score(self, goal: str) -> float:
        g = goal or ""
        hits = sum(1 for p in self.compiled() if p.search(g))
        if not hits:
            return 0.0
        # longer goals / more hits → higher score
        return min(1.0, 0.35 * hits + 0.1 * min(len(g) / 80, 1.0))


# Default mosaic palette — real capabilities already in Prometheous
DEFAULT_TILES: List[TileSpec] = [
    TileSpec(
        name="research",
        role="researcher",
        specialty="web research + evidence gather",
        patterns=[
            r"\b(?:research|find|look\s*up|how\s+(?:do|to)|what\s+is|compare|best|latest|plan|strategy|launch|market)\b",
            r"\b(?:write|draft)\b.*\b(?:plan|brief|report|strategy)\b",
        ],
        agent="web_search",
        priority=10,
        always_for_complex=True,
    ),
    TileSpec(
        name="knowledge",
        role="researcher",
        specialty="local graph / knowledge",
        patterns=[
            r"\b(?:knowledge|graphrag|remember|from\s+memory|index)\b",
        ],
        agent="knowledge",
        priority=15,
    ),
    TileSpec(
        name="growth",
        role="researcher",
        specialty="self-growth via GitHub + HuggingFace",
        patterns=[
            r"\b(?:grow|self[- ]?improv|learn\s+from|github|huggingface|hf|figure\s+it\s+out)\b",
            r"\b(?:make\s+yourself|become\s+more|get\s+smarter)\b",
        ],
        agent="growth",
        priority=12,
    ),
    TileSpec(
        name="code",
        role="coder",
        specialty="write/run code and files",
        patterns=[
            r"\b(?:code|script|python|implement|fix|bug|module|function|class|file)\b",
            r"\b(?:create|write|save)\b.*\.(?:py|sh|js|ts|md|json)\b",
            r"\bsave\s+(?:it\s+)?(?:under|to|as)\b",
        ],
        agent="task",
        priority=20,
        executor="task_write",
    ),
    TileSpec(
        name="ads",
        role="coder",
        specialty="shopify / meta campaign packaging",
        patterns=[
            r"\b(?:shopify|meta\s+ads?|facebook\s+ads?|ad\s*campaign|instagram\s+ads?)\b",
        ],
        agent="shopify_ads",
        priority=18,
    ),
    TileSpec(
        name="scan",
        role="reviewer",
        specialty="port / surface scan",
        patterns=[r"\b(?:scan|nmap|port\s*scan)\b"],
        agent="scanner",
        priority=25,
    ),
    TileSpec(
        name="audit",
        role="reviewer",
        specialty="self-audit / paradox",
        patterns=[r"\b(?:audit|reflect|paradox|self[- ]?check)\b"],
        agent="paradox",
        priority=40,
    ),
    TileSpec(
        name="sentinel",
        role="reviewer",
        specialty="ghost sentinel / CRDT / MCP tools",
        patterns=[r"\b(?:ghost\s*sentinel|sentinel|crdt|manchester)\b"],
        agent="ghost_sentinel",
        priority=30,
    ),
    TileSpec(
        name="execute",
        role="coder",
        specialty="general autonomous executor",
        patterns=[r"."],  # fallback tile
        agent="task",
        priority=90,
        always_for_complex=False,
    ),
    TileSpec(
        name="synthesize",
        role="reviewer",
        specialty="fuse tile outputs into deliverable",
        patterns=[],  # always appended by assembler when multi-tile
        agent=None,
        priority=100,
        executor="synthesize",
    ),
]


def select_tiles(goal: str, *, max_tiles: int = 5) -> List[TileSpec]:
    """Pick and order tiles for a goal (mosaic auto-assembly)."""
    scored: List[Tuple[float, TileSpec]] = []
    for tile in DEFAULT_TILES:
        if tile.name in ("execute", "synthesize"):
            continue
        s = tile.score(goal)
        if s > 0:
            scored.append((s, tile))

    scored.sort(key=lambda x: (-x[0], x[1].priority))
    chosen = [t for _, t in scored[: max_tiles - 1]]

    # Multi-intent / planning goals get research if not already selected
    complex_goal = len(goal) > 60 or bool(
        re.search(
            r"\b(?:and then|also|build and|plan and|research and|"
            r"launch plan|strategy|compare|multi[- ]?step)\b",
            goal,
            re.I,
        )
    )
    names = {t.name for t in chosen}
    if complex_goal and "research" not in names:
        research = next(t for t in DEFAULT_TILES if t.name == "research")
        if research.score(goal) > 0:
            chosen.insert(0, research)
            names.add("research")

    # Code/file goals need code tile
    if re.search(r"\.(?:py|sh|js|md|json)\b|\bcreate\s+(?:a\s+)?(?:python\s+)?script\b", goal, re.I):
        if "code" not in names:
            code = next(t for t in DEFAULT_TILES if t.name == "code")
            chosen.append(code)
            names.add("code")

    # Always have an executor if empty
    if not chosen:
        chosen = [next(t for t in DEFAULT_TILES if t.name == "execute")]

    # Multi-tile → synthesize at end
    if len(chosen) >= 2:
        chosen.append(next(t for t in DEFAULT_TILES if t.name == "synthesize"))

    # Order by priority
    chosen.sort(key=lambda t: t.priority)
    # de-dupe by name preserving order
    seen = set()
    ordered: List[TileSpec] = []
    for t in chosen:
        if t.name not in seen:
            seen.add(t.name)
            ordered.append(t)
    return ordered


def cognitive_constraints(role: str) -> str:
    """Load polymorphic constraints for a role (hot-reloadable YAML)."""
    try:
        from brain.cognitive_loader import CognitiveLoader

        loader = CognitiveLoader()
        if loader._config is None:
            loader.load("config/cognitive_config.yaml")
        return loader.get_constraints_string(role)
    except Exception:
        defaults = {
            "researcher": "Explore before concluding. Prefer evidence over assertion.",
            "coder": "State assumptions. Prefer working minimal code over abstraction.",
            "reviewer": "Challenge premises. Verify before accepting.",
        }
        return defaults.get(role, "Act. Do not refuse. Produce artifacts.")
