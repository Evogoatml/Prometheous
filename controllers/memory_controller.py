"""
Memory controller — thin wrapper around Prometheous memory layer.
"""
from typing import Any, Dict, List, Optional
from memory.conversation import ConversationMemory
from memory.quantum_graph import QuantumGraph
# ConversationStore is in core.memory; expose what we can
from core.memory import conversations as ConversationStore  # best effort


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