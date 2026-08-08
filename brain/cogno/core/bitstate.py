# cogno/core/bitstate.py
import numpy as np

class BitState:
    """
    A quantum-inspired state using bitwise operations.
    Each bit position = one possible state.
    Multiple bits SET = superposition.
    One bit SET = collapsed.
    """

    def __init__(self, width: int = 64):
        self.width = width
        self.register = 0          # raw bitmask — all states
        self.amplitude = np.zeros(width, dtype=np.complex128)

    # ── Superposition ──────────────────────────────────────────
    def superpose(self, *state_indices: int, weights: list[float] = None):
        """Set multiple states simultaneously via OR masking."""
        for i, idx in enumerate(state_indices):
            self.register |= (1 << idx)          # SET bit = state exists
            w = weights[i] if weights else 1.0
            self.amplitude[idx] = complex(w, 0)

        # Normalize amplitudes so |a|² sums to 1
        norm = np.sqrt(sum(abs(a)**2 for a in self.amplitude))
        if norm > 0:
            self.amplitude /= norm

    # ── Collapse (wave function → single bit) ──────────────────
    def observe(self) -> int:
        active = [i for i in range(self.width) if self.register & (1 << i)]
        probs  = [abs(self.amplitude[i])**2 for i in active]
        total  = sum(probs)
        probs  = [p / total for p in probs]

        chosen = np.random.choice(active, p=probs)
        self.register = (1 << chosen)             # CLEAR all, SET one
        self.amplitude = np.zeros(self.width, dtype=np.complex128)
        self.amplitude[chosen] = 1.0
        return chosen

    # ── Entanglement via XOR ────────────────────────────────────
    def entangle(self, other: "BitState") -> "BitState":
        """XOR two registers = entangled difference state."""
        result = BitState(self.width)
        result.register = self.register ^ other.register
        result.amplitude = self.amplitude - other.amplitude
        return result

    # ── Interference ────────────────────────────────────────────
    def interfere(self, other: "BitState", mode: str = "constructive"):
        """AND = constructive (overlap). AND NOT = destructive (cancel)."""
        if mode == "constructive":
            self.register &= other.register        # keep shared states
            self.amplitude += other.amplitude
        else:
            self.register &= ~other.register       # cancel overlapping
            self.amplitude -= other.amplitude

    # ── Parity check (error detection) ──────────────────────────
    def parity(self) -> int:
        """Population count parity — odd=1, even=0."""
        return bin(self.register).count('1') % 2

    # ── Bit mask utilities ───────────────────────────────────────
    def active_states(self) -> list[int]:
        return [i for i in range(self.width) if (self.register >> i) & 1]

    def hamming_distance(self, other: "BitState") -> int:
        """Count bit differences — cognitive divergence metric."""
        return bin(self.register ^ other.register).count('1')

    def __repr__(self):
        return f"BitState({self.register:064b}) active={self.active_states()}"