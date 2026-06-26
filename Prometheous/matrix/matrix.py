# prometheus/core/matrix.py
import time
import json
from typing import Dict, Any, List, Optional
from prometheus.memory.quantum_graph import QuantumGraph, QuantumNode
from prometheus.memory.graph_rag import GraphRAGStore
from prometheus.memory.vault import EncryptedVault
from prometheus.memory.conversation import ConversationStore


class NeuroMatrix:
    """The substrate — graph + GraphRAG + vault + conversation."""

    def __init__(self):
        self.graph = QuantumGraph()
        self.graph_rag = GraphRAGStore()
        self.vault = EncryptedVault()
        self.conversations = ConversationStore()

        # Seed the graph with a root node
        root = QuantumNode("root", "Prometheus root knowledge")
        self.graph.add_node(root)

    def observe(self, query: str) -> Dict[str, Any]:
        """Pull context from all sources."""
        self.graph.propagate("root", 0.5)

        gr_results = self.graph_rag.query(query, top_k=3)

        return {
            "query": query,
            "graph_state": self.graph.observe_all(),
            "graphrag": [txt for txt, _ in gr_results],
        }

    def reflect(self, query: str, result: Any, metadata: Dict = None) -> None:
        """Write result back into the graph."""
        node_id = f"result_{int(time.time())}"
        node = QuantumNode(node_id, json.dumps({
            "query": query,
            "result": result,
            "metadata": metadata or {}
        }))
        self.graph.add_node(node)
        self.graph.connect("root", node_id, weight=0.5)

    def get_context(self, chat_id: int, limit: int = 5) -> List[Dict]:
        """Get conversation context."""
        conv = self.conversations.get(chat_id)
        return conv.get_history(limit)

    def add_conversation(self, chat_id: int, role: str, content: str):
        """Add to conversation history."""
        conv = self.conversations.get(chat_id)
        conv.add(role, content)