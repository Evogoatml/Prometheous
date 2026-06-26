"""
Memory controller — wraps prometheus.memory for agent recall/remember.
"""
from typing import Any, Dict, List, Optional
from prometheus.memory.conversation import ConversationStore, ConversationMemory
from prometheus.memory.quantum_graph import QuantumGraph


class MemoryController:
    """Agent-facing memory interface. Recall/remember pattern."""

    def __init__(self):
        self._store: Dict[str, List[dict]] = {}

    def recall(self, query: str, agent_id: str = "default", k: int = 3) -> List[dict]:
        """Recall recent memories for an agent."""
        raw = self._store.get(agent_id, [])
        return [{"content": entry} for entry in raw[-k:]]

    def remember(self, content: str, agent_id: str = "default",
                 metadata: Optional[Dict[str, Any]] = None) -> None:
        """Store a memory for an agent."""
        if agent_id not in self._store:
            self._store[agent_id] = []
        self._store[agent_id].append(content)

    def clear(self, agent_id: str = "default") -> None:
        self._store.pop(agent_id, None)


memory = MemoryController()