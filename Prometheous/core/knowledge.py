"""
High-level knowledge system.

Wraps the lower-level memory.KnowledgeBase with semantic helpers and
a coherent knowledge-gaps report. The LLM never writes here directly —
only the orchestrator / agents do.
"""
import logging
import time
from typing import Any, Dict, List, Optional

from core.memory import knowledge

logger = logging.getLogger(__name__)


class KnowledgeSystem:
    """
    Structured knowledge store.

    Stores:
      - facts (key/value)
      - tagged insights
      - capability tags (what the system knows it can do)
      - gaps (what it knows it doesn't know)
    """

    def __init__(self):
        self._kb = knowledge

    # facts ----------------------------------------------------------------
    def add_fact(self, key: str, value: Any, tags: Optional[List[str]] = None, source: str = "system") -> str:
        return self._kb.put(key, value, tags=tags, source=source)

    def get_fact(self, key: str) -> Optional[Any]:
        return self._kb.get(key)

    def search(self, tag: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self._kb.search(tag, limit=limit)

    # capabilities ---------------------------------------------------------
    def register_capability(self, agent: str, capability: str) -> None:
        caps = self._kb.get("capabilities") or {}
        caps.setdefault(agent, []).append({"capability": capability, "ts": time.time()})
        self._kb.put("capabilities", caps, tags=["capability"], source=agent)

    def list_capabilities(self) -> Dict[str, List[Dict[str, Any]]]:
        return self._kb.get("capabilities") or {}

    # gaps -----------------------------------------------------------------
    def record_gap(self, topic: str) -> None:
        gaps = self._kb.get("knowledge_gaps") or []
        if topic not in gaps:
            gaps.append(topic)
            self._kb.put("knowledge_gaps", gaps, tags=["gap"], source="system")
            logger.info("knowledge gap recorded: %s", topic)

    def list_gaps(self) -> List[str]:
        return self._kb.get("knowledge_gaps") or []

    def fill_gap(self, topic: str) -> None:
        gaps = self._kb.get("knowledge_gaps") or []
        if topic in gaps:
            gaps.remove(topic)
            self._kb.put("knowledge_gaps", gaps, tags=["gap"], source="system")
            logger.info("knowledge gap filled: %s", topic)


# Single shared instance
ksys = KnowledgeSystem()
