"""
Knowledge Graph for Agent Byte.
Simple graph structure for relational knowledge.
"""

from typing import Dict, List, Any, Optional, Set, Tuple


class KnowledgeGraph:
    """Sparse knowledge graph for agent-learned relationships."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Tuple[str, str, str, float]] = []
        self._node_id_counter = 0

    def add_node(self, label: str, properties: Optional[Dict[str, Any]] = None) -> str:
        """Add a node and return its ID."""
        node_id = f"node_{self._node_id_counter}"
        self._node_id_counter += 1
        self.nodes[node_id] = {
            "id": node_id,
            "label": label,
            "properties": properties or {},
        }
        return node_id

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        weight: float = 1.0,
    ) -> None:
        """Add a weighted edge between nodes."""
        if source in self.nodes and target in self.nodes:
            self.edges.append((source, target, relation, weight))

    def get_neighbors(self, node_id: str) -> List[str]:
        """Get all neighbor node IDs."""
        neighbors = []
        for src, tgt, _, _ in self.edges:
            if src == node_id:
                neighbors.append(tgt)
            elif tgt == node_id:
                neighbors.append(src)
        return neighbors

    def query(self, label: Optional[str] = None, relation: Optional[str] = None) -> List[Dict[str, Any]]:
        """Simple graph query."""
        results = []
        for node_id, node_data in self.nodes.items():
            if label is None or node_data["label"] == label:
                results.append(node_data)
        return results

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
        }
