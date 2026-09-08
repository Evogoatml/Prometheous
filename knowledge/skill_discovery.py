"""Prometheous skill discovery — extracts skills from interpreted patterns."""
import re
from typing import Any, Dict, List


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return slug or "skill"


def _description_tokens(description: str) -> set:
    return {tok for tok in re.findall(r"[a-z0-9]+", (description or "").lower()) if len(tok) > 3}


class SkillDiscovery:
    def __init__(self):
        pass

    def discover(self, pattern_interpretation: Dict, existing: Dict) -> List[Dict]:
        skills = []
        indicators = pattern_interpretation.get('skill_indicators', [])
        existing_ids = set(existing or {})
        known_fields = {'type', 'description', 'confidence'}
        for i, ind in enumerate(indicators[:3]):
            skill_type = ind.get('type', 'discovered_skill')
            slug = f"skill_{_slugify(skill_type)}_{i}"
            # avoid colliding with an already-known skill id
            while slug in existing_ids:
                slug = f"{slug}_"
            existing_ids.add(slug)
            parameters = dict(ind.get('parameters') or {})
            parameters.update({
                k: v for k, v in ind.items()
                if k not in known_fields and k != 'parameters'
            })
            skills.append({
                "id": slug,
                "name": skill_type,
                "type": "general",
                "description": ind.get('description', ''),
                "confidence": ind.get('confidence', 0.5),
                "parameters": parameters,
                "abstraction_level": "tactical",
            })
        return skills

    def analyze_skill_relationships(self, discovered: Dict) -> Dict:
        # `discovered` is env_knowledge['discovered_skills']: skill_id -> {'skill': {...}, ...}
        # but tolerate being handed flat skill dicts too.
        entries = list(discovered.values()) if isinstance(discovered, dict) else list(discovered or [])
        skills = [e.get('skill', e) if isinstance(e, dict) else e for e in entries]
        relations: List[Dict[str, Any]] = []
        for i, a in enumerate(skills):
            tokens_a = _description_tokens(a.get('description', ''))
            for b in skills[i + 1:]:
                if a.get('id') == b.get('id'):
                    continue
                # `type` is a fixed "general" category (see discover()); the
                # actual skill category lives in `name`.
                if a.get('name') and a.get('name') == b.get('name'):
                    relations.append({
                        "skill_a": a.get('id'),
                        "skill_b": b.get('id'),
                        "relation": "same_type",
                    })
                    continue
                shared = tokens_a & _description_tokens(b.get('description', ''))
                if shared:
                    relations.append({
                        "skill_a": a.get('id'),
                        "skill_b": b.get('id'),
                        "relation": "related_description",
                        "shared_terms": sorted(shared)[:5],
                    })
        return {"relations": relations, "count": len(relations)}
