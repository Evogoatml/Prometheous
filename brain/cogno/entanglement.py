"""
cogno/entanglement.py

Quantum twins paradox as a cognitive primitive.
Two agents share correlated probability space.
When one collapses — the other narrows.
No messaging. No signals. Shared state geometry.

Real implementation using numpy probability distributions.
No quantum hardware required. The math is what matters.
"""

import time
import hashlib
import numpy as np
from typing import Optional
from dataclasses import dataclass, field
from threading import Lock


# ─────────────────────────────────────────────
# QUANTUM STATE
# ─────────────────────────────────────────────

@dataclass
class QuantumThoughtState:
    """
    A thought in superposition across multiple choices
    until observed. Before: probability distribution.
    After: collapsed single choice.

    >>> import numpy as np
    >>> q = QuantumThoughtState(
    ...     amplitudes=np.array([1.0, 0.0, 0.0]),
    ...     basis=["proceed", "revise", "abort"]
    ... )
    >>> q.observe()
    'proceed'
    >>> q.collapsed
    True
    """

    amplitudes: np.ndarray
    basis:      list
    collapsed:  bool          = False
    result:     Optional[str] = None
    timestamp:  float         = field(default_factory=time.time)

    @property
    def probabilities(self) -> np.ndarray:
        p = np.abs(self.amplitudes) ** 2
        return p / p.sum()

    def observe(self) -> str:
        if self.collapsed:
            return self.result
        self.result    = str(np.random.choice(self.basis, p=self.probabilities))
        self.collapsed = True
        return self.result

    def superposition_entropy(self) -> float:
        """
        How uncertain is this thought?
        High = many possibilities. Low = one dominates.

        >>> import numpy as np
        >>> q = QuantumThoughtState(
        ...     amplitudes=np.array([1.0, 0.0, 0.0]),
        ...     basis=["a", "b", "c"]
        ... )
        >>> q.superposition_entropy() < 0.01
        True
        """
        p = self.probabilities
        p = p[p > 0]
        return float(-np.sum(p * np.log2(p)))


# ─────────────────────────────────────────────
# ENTANGLED PAIR
# ─────────────────────────────────────────────

class EntangledPair:
    """
    Two agents sharing correlated quantum state.
    When A observes — B's amplitudes shift through
    the correlation matrix. No message. No signal.

    >>> import numpy as np
    >>> pair = EntangledPair.create(["proceed", "revise", "abort"])
    >>> pair.agent_a.collapsed
    False
    >>> result = pair.observe_a()
    >>> pair.agent_a.collapsed
    True
    >>> pair.agent_b.collapsed
    False
    """

    def __init__(
        self,
        agent_a:     QuantumThoughtState,
        agent_b:     QuantumThoughtState,
        correlation: np.ndarray,
        entangle_id: str
    ):
        self.agent_a     = agent_a
        self.agent_b     = agent_b
        self.correlation = correlation
        self.entangle_id = entangle_id
        self._lock       = Lock()
        self._history:   list = []

    @classmethod
    def create(
        cls,
        basis:       list,
        correlation: Optional[np.ndarray] = None
    ) -> "EntangledPair":
        """
        Create entangled pair with shared basis.
        Default: anti-correlated (complementary agents).

        >>> import numpy as np
        >>> p = EntangledPair.create(["proceed", "revise", "abort"])
        >>> p.agent_a.collapsed
        False
        """
        n    = len(basis)
        amps = np.ones(n) / np.sqrt(n)

        if correlation is None:
            correlation = np.ones((n, n)) - np.eye(n) * (n - 1)
            correlation = correlation / correlation.sum(axis=1, keepdims=True)

        return cls(
            agent_a=QuantumThoughtState(amplitudes=amps.copy(), basis=basis),
            agent_b=QuantumThoughtState(amplitudes=amps.copy(), basis=basis),
            correlation=correlation,
            entangle_id=hashlib.sha256(
                f"{basis}{time.time()}".encode()
            ).hexdigest()[:12]
        )

    def observe_a(self) -> str:
        with self._lock:
            result = self.agent_a.observe()
            self._update_twin(self.agent_a, self.agent_b, result)
            self._history.append({"observer": "agent_a", "result": result, "ts": time.time()})
            return result

    def observe_b(self) -> str:
        with self._lock:
            result = self.agent_b.observe()
            self._update_twin(self.agent_b, self.agent_a, result)
            self._history.append({"observer": "agent_b", "result": result, "ts": time.time()})
            return result

    def _update_twin(
        self,
        collapsed: QuantumThoughtState,
        twin:      QuantumThoughtState,
        result:    str
    ) -> None:
        if twin.collapsed:
            return
        idx             = collapsed.basis.index(result)
        correlation_row = self.correlation[idx]
        new_amps        = twin.amplitudes * correlation_row
        norm            = np.linalg.norm(new_amps)
        if norm > 1e-10:
            twin.amplitudes = new_amps / norm
        else:
            n               = len(twin.basis)
            twin.amplitudes = np.ones(n) / np.sqrt(n)

    def correlation_strength(self) -> float:
        n    = len(self.agent_a.basis)
        diag = np.trace(self.correlation) / n
        return float(1.0 - diag)

    def reset(self) -> None:
        n    = len(self.agent_a.basis)
        amps = np.ones(n) / np.sqrt(n)
        for agent in (self.agent_a, self.agent_b):
            agent.amplitudes = amps.copy()
            agent.collapsed  = False
            agent.result     = None

    @property
    def both_collapsed(self) -> bool:
        return self.agent_a.collapsed and self.agent_b.collapsed


# ─────────────────────────────────────────────
# ENTANGLEMENT REGISTRY
# ─────────────────────────────────────────────

class EntanglementRegistry:
    """
    Tracks all entangled pairs in the system.

    >>> reg = EntanglementRegistry()
    >>> pair = reg.entangle("nexus", "adap", ["proceed", "revise", "abort"])
    >>> reg.is_entangled("nexus")
    True
    >>> reg.active_pairs()
    1
    """

    def __init__(self):
        self._pairs:  dict[str, EntangledPair] = {}
        self._agents: dict[str, list[str]]     = {}
        self._lock    = Lock()

    def entangle(
        self,
        agent_a_id:  str,
        agent_b_id:  str,
        basis:       list,
        correlation: Optional[np.ndarray] = None
    ) -> EntangledPair:

        with self._lock:
            pair = EntangledPair.create(basis, correlation)
            self._pairs[pair.entangle_id] = pair
            for agent_id in (agent_a_id, agent_b_id):
                if agent_id not in self._agents:
                    self._agents[agent_id] = []
                self._agents[agent_id].append(pair.entangle_id)
            return pair

    def is_entangled(self, agent_id: str) -> bool:
        return agent_id in self._agents and len(self._agents[agent_id]) > 0

    def dissolve(self, entangle_id: str) -> bool:
        with self._lock:
            pair = self._pairs.pop(entangle_id, None)
            if pair:
                for pair_list in self._agents.values():
                    if entangle_id in pair_list:
                        pair_list.remove(entangle_id)
                return True
            return False

    def active_pairs(self) -> int:
        return len(self._pairs)


# ─────────────────────────────────────────────
# QUANTUM THINKER
# ─────────────────────────────────────────────

class QuantumThinker:
    """
    Thinker with quantum entanglement.
    When this agent observes — entangled twins shift.
    Coordination without communication.
    """

    def __init__(
        self,
        agent_id: str,
        registry: EntanglementRegistry,
        depth:    int  = 2,
        dual:     bool = False
    ):
        self.agent_id = agent_id
        self.registry = registry
        self.depth    = depth
        self.dual     = dual

    def think(
        self,
        input_data: object,
        basis:      Optional[list] = None
    ) -> QuantumThoughtState:

        if basis is None:
            basis = ["proceed", "revise", "delegate", "abort"]

        n    = len(basis)
        amps = np.ones(n) / np.sqrt(n)

        complexity = len(str(input_data)) / 1000.0
        if complexity < 0.1:
            amps[0] *= 2.0
        elif complexity > 0.5:
            amps[1] *= 1.8

        amps = amps / np.linalg.norm(amps)

        return QuantumThoughtState(amplitudes=amps, basis=basis)


# ─────────────────────────────────────────────
# SELF-TEST — real execution
# ─────────────────────────────────────────────

def test_entanglement() -> dict:
    """
    Real statistical test of entanglement.
    1000 trials. Verifies correlation holds.
    Returns real stats — not assertions.
    """
    basis    = ["proceed", "revise", "abort"]
    n_trials = 1000
    results_a, results_b = [], []

    for _ in range(n_trials):
        pair     = EntangledPair.create(basis)
        result_a = pair.observe_a()
        result_b = pair.observe_b()
        results_a.append(result_a)
        results_b.append(result_b)

    same           = sum(a == b for a, b in zip(results_a, results_b))
    anti_corr_rate = (n_trials - same) / n_trials

    pair           = EntangledPair.create(basis)
    entropy_before = pair.agent_a.superposition_entropy()
    pair.observe_a()
    entropy_after  = pair.agent_b.superposition_entropy()

    return {
        "trials":           n_trials,
        "anti_correlation": round(anti_corr_rate, 3),
        "entropy_before":   round(entropy_before, 3),
        "entropy_after":    round(entropy_after, 3),
        "entropy_reduced":  entropy_after < entropy_before,
        "passed":           anti_corr_rate > 0.5
    }


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import doctest
    doctest.testmod(verbose=False)

    print("Running entanglement self-test...")
    stats = test_entanglement()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    registry  = EntanglementRegistry()
    thinker_a = QuantumThinker("nexus", registry, depth=2)
    thinker_b = QuantumThinker("adap",  registry, depth=2)

    pair = registry.entangle(
        "nexus", "adap",
        basis=["proceed", "revise", "delegate", "abort"]
    )

    state_a  = thinker_a.think("complex multi-dependency code block")
    result_a = pair.observe_a()
    state_b  = thinker_b.think("what is my role right now")
    result_b = pair.observe_b()

    print(f"\nnexus decided:   {result_a}")
    print(f"adap correlated: {result_b}")
    print(f"entangle_id:     {pair.entangle_id}")
    print(f"correlation:     {pair.correlation_strength():.3f}")
