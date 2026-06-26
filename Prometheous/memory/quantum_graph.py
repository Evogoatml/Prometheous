from typing import Dict, List, Optional

class QuantumNode:
    def __init__(self, node_id: str, content: str = "", activation_threshold: float = 0.5):
        self.node_id = node_id
        self.content = content
        self.activation_threshold = activation_threshold
        self.state: float = 0.0
        self.weights: Dict[str, float] = {}
        self.plasticity: float = 0.1

    def receive_signal(self, source_id: str, signal: float):
        self.state += signal * self.weights.get(source_id, 0.1)

    def activate(self) -> Optional[float]:
        if self.state >= self.activation_threshold:
            self.state = 0.0
            return 1.0
        return None

    def strengthen_synapse(self, source_id: str):
        self.weights[source_id] = min(1.0, self.weights.get(source_id, 0.1) + self.plasticity)

class QuantumGraph:
    def __init__(self):
        self.nodes: Dict[str, QuantumNode] = {}
        self.edges: Dict[str, List[str]] = {}

    def add_node(self, node: QuantumNode):
        self.nodes[node.node_id] = node
        self.edges[node.node_id] = []

    def connect(self, source_id: str, target_id: str, weight: float = 0.5):
        self.edges[source_id].append(target_id)
        self.nodes[target_id].weights[source_id] = weight

    def propagate(self, source_id: str, signal: float):
        visited = set()
        queue = [(source_id, signal)]
        while queue:
            current_id, sig = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            node = self.nodes[current_id]
            node.receive_signal(source_id, sig)
            output = node.activate()
            if output is not None:
                for neighbor_id in self.edges.get(current_id, []):
                    queue.append((neighbor_id, output))
                    node.strengthen_synapse(current_id)

    def observe_all(self) -> Dict[str, float]:
        return {nid: node.state for nid, node in self.nodes.items()}

    def get_node(self, node_id: str) -> Optional[QuantumNode]:
        return self.nodes.get(node_id)

    def add_knowledge_node(self, node_id: str, content: str):
        node = QuantumNode(node_id, content)
        self.add_node(node)
        return node
