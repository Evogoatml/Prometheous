"""
Knowledge agent — queries BRAIN knowledge store only.

Does not open knowledge/training/. That folder is training corpus, not bot code.
"""
from __future__ import annotations

from typing import Any, Dict, List

used_modules: List[str] = []

try:
    from brain.knowledge_store import brain_knowledge

    used_modules.append("brain.knowledge_store")
except Exception:
    brain_knowledge = None  # type: ignore

try:
    from knowledge import knowledge_system as adv_ks

    used_modules.append("knowledge_system")
except Exception:
    adv_ks = None

try:
    from knowledge import crdt_knowledge

    used_modules.append("crdt_knowledge")
except Exception:
    crdt_knowledge = None


class KnowledgeAgent:
    name = "knowledge"
    role = "Knowledge"
    specialty = "brain knowledge (algorithms, ciphers, maths) — not training folder"
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        topic = str(
            payload.get("topic")
            or payload.get("query")
            or payload.get("user_msg")
            or payload.get("goal")
            or "general"
        ).strip()
        mode = str(payload.get("mode") or "query").lower()

        results: Dict[str, Any] = {
            "modules_loaded": list(used_modules),
            "training_folder_in_bot": False,
        }

        hits: List[Dict[str, Any]] = []
        formatted = ""

        if brain_knowledge is None:
            formatted = "Brain knowledge store unavailable."
        elif mode in ("rebuild", "index", "build"):
            # Do not rebuild from bot by walking training — point to offline command
            formatted = (
                "Brain index is built OFFLINE (not by the bot).\n"
                "Run: python -m brain.build_ability_knowledge\n"
                "That reads knowledge/training once and writes data/learning/ability_index.jsonl.\n"
                "Training folder stays out of the bot."
            )
            results["rebuild"] = "offline_only"
            if brain_knowledge.online:
                brain_knowledge.load(force=True)
                results["stats"] = brain_knowledge.stats()
        else:
            brain_knowledge.load()
            hits = brain_knowledge.query(topic, top_k=int(payload.get("top_k") or 8))
            formatted = brain_knowledge.format_hits(hits, topic)
            results["brain"] = {
                "hits": len(hits),
                "stats": brain_knowledge.stats(),
                "top": [
                    {"path": h.get("path"), "domain": h.get("domain"), "score": h.get("score")}
                    for h in hits[:5]
                ],
            }

        if adv_ks and hasattr(adv_ks, "KnowledgeSystem"):
            try:
                ks = adv_ks.KnowledgeSystem()
                if hasattr(ks, "process_neural_insights"):
                    ks.process_neural_insights("query", {"pattern_summary": {"topic": topic[:80]}})
                results["advanced_ks"] = "ok"
            except Exception as e:
                results["advanced_ks_error"] = str(e)[:100]

        if crdt_knowledge:
            results["crdt"] = "available"

        return {
            "status": "ok",
            "agent": self.name,
            "topic": topic,
            "results": results,
            "hits": hits,
            "formatted": (formatted or "")[:4000],
        }
