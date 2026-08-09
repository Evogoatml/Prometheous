"""Skill hierarchy discovery and composition helpers."""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class SkillTemplate:
    name: str
    description: str
    base_agents: List[str] = field(default_factory=list)
    composition_rule: str = "sequential"
    triggers: List[str] = field(default_factory=list)


class SkillComposer:
    """Select, discover, and combine reusable skill templates."""

    def compose(self, templates: List[SkillTemplate], goal: str) -> SkillTemplate:
        goal_text = (goal or "").lower()
        ranked: List[SkillTemplate] = []
        for template in templates or []:
            hits = sum(1 for trigger in template.triggers if trigger.lower() in goal_text)
            if hits:
                ranked.extend([template] * hits)
        if not ranked:
            return SkillTemplate(
                name="default_skill",
                description=f"Fallback skill for: {goal}",
                base_agents=["task"],
                composition_rule="sequential",
                triggers=[goal[:40]],
            )
        unique: List[SkillTemplate] = []
        seen = set()
        for template in ranked:
            if template.name in seen:
                continue
            seen.add(template.name)
            unique.append(template)
        if len(unique) == 1:
            return unique[0]
        return self.generate_meta_skill("composed_" + "_".join(t.name for t in unique[:3]), unique)

    def discover_from_trajectories(self, trajectory_file: str) -> List[SkillTemplate]:
        path = Path(trajectory_file)
        if not path.exists():
            return []
        sequences: Counter[tuple[str, ...]] = Counter()
        current: List[str] = []
        templates: List[SkillTemplate] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            agent = str(entry.get("agent") or "").strip()
            if not agent:
                continue
            current.append(agent)
            if len(current) >= 2:
                sequences[tuple(current[-3:])] += 1
        for seq, count in sequences.items():
            if count < 2:
                continue
            templates.append(
                SkillTemplate(
                    name="skill_" + "_".join(seq),
                    description=f"Recurring trajectory of {count} occurrences",
                    base_agents=list(seq),
                    composition_rule="sequential" if len(seq) <= 2 else "parallel",
                    triggers=[re.sub(r"[_-]+", " ", seq[0])],
                )
            )
        return templates

    def generate_meta_skill(self, name: str, sub_skills: List[SkillTemplate]) -> SkillTemplate:
        agents: List[str] = []
        triggers: List[str] = []
        rules = {skill.composition_rule for skill in sub_skills or []}
        for skill in sub_skills or []:
            for agent in skill.base_agents:
                if agent not in agents:
                    agents.append(agent)
            for trigger in skill.triggers:
                if trigger not in triggers:
                    triggers.append(trigger)
        rule = "parallel" if "parallel" in rules else ("conditional" if "conditional" in rules else "sequential")
        return SkillTemplate(
            name=name,
            description="Meta-skill composed from: " + ", ".join(skill.name for skill in sub_skills or []),
            base_agents=agents,
            composition_rule=rule,
            triggers=triggers,
        )
