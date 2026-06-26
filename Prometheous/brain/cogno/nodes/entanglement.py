# cogno/nodes/entanglement.py

class EntanglementBus:
    """
    Manages entangled node pairs.
    When node A collapses, node B gets the correlated/opposite state.
    """
    def __init__(self):
        self.pairs: dict[str, str] = {}  # {node_id: partner_id}
        self.registry: dict[str, "QuantumNode"] = {}

    def entangle(self, node_a: "QuantumNode", node_b: "QuantumNode"):
        node_a.entangled_with.append(node_b.node_id)
        node_b.entangled_with.append(node_a.node_id)
        self.pairs[node_a.node_id] = node_b.node_id
        self.pairs[node_b.node_id] = node_a.node_id
        self.registry[node_a.node_id] = node_a
        self.registry[node_b.node_id] = node_b

    def collapse_propagate(self, node: "QuantumNode") -> str:
        """Observe node A → force correlated collapse on node B."""
        result = node.observe()
        partner_id = self.pairs.get(node.node_id)
        if partner_id:
            partner = self.registry[partner_id]
            # Correlated: partner gets the opposite/complementary state
            if partner.state_amplitudes:
                states = list(partner.state_amplitudes.keys())
                # Remove observed state, collapse partner into one of the rest
                remaining = [s for s in states if s != result]
                if remaining:
                    partner.collapsed_state = remaining[0]
        return result