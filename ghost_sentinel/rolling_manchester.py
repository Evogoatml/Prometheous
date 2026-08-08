"""
Rolling polymorphic Manchester encoder/decoder.

Self-clocking bit transitions mutate per-block via a BLAKE3-style ratchet.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional, Tuple

from ghost_sentinel.blake3_bridge import ratchet as blake3_ratchet

ManchesterPair = Tuple[int, int]
VariantFn = Callable[[int], ManchesterPair]


@dataclass
class RatchetSnapshot:
    state: bytes
    counter: int


class RollingManchester:
    """Rolling Manchester with polymorphic variant selection driven by ratchet."""

    def __init__(self, initial_seed: bytes, *, history_depth: int = 8):
        if len(initial_seed) < 32:
            raise ValueError("initial_seed must be at least 32 bytes")
        self.state = initial_seed[:32]
        self.counter = 0
        self._history: Deque[RatchetSnapshot] = deque(maxlen=history_depth)
        self.variants: List[VariantFn] = [
            lambda b: (b, 1 - b),       # 0→01, 1→10
            lambda b: (1 - b, b),       # 0→10, 1→01 (inverted)
        ]

    def _snapshot(self) -> RatchetSnapshot:
        return RatchetSnapshot(state=self.state, counter=self.counter)

    def _restore(self, snap: RatchetSnapshot) -> None:
        self.state = snap.state
        self.counter = snap.counter

    def _peek_ratchet(self, extra: bytes = b"") -> bytes:
        """Ratchet material without advancing — both peers derive the same roll."""
        return blake3_ratchet(self.state, extra, self.counter)

    def _ratchet(self, extra: bytes = b"") -> bytes:
        new_state = blake3_ratchet(self.state, extra, self.counter)
        self._history.append(self._snapshot())
        self.state = new_state
        self.counter += 1
        return new_state

    def encode(self, data: bytes) -> bytes:
        roll = self._peek_ratchet(b"")
        bits_out: List[int] = []
        bit_index = 0
        for byte in data:
            for bit_pos in range(8):
                bit = (byte >> (7 - bit_pos)) & 1
                var_idx = (roll[bit_index % 32] >> (bit_index % 8)) & 1
                t0, t1 = self.variants[var_idx](bit)
                bits_out.extend([t0, t1])
                bit_index += 1
        self._ratchet(b"")
        return self._pack_bits(bits_out)

    def decode(self, wire: bytes, window: int = 2) -> Optional[bytes]:
        """
        Decode with bounded ratchet window search for minor desync.
        """
        saved = self._snapshot()

        offsets = [0]
        if window > 0:
            offsets.extend(o for o in range(-window, window + 1) if o != 0)

        for offset in offsets:
            try:
                self._restore(saved)
                self.counter = max(0, saved.counter + offset)
                roll = self._peek_ratchet(b"")
                bits = self._unpack_bits(wire)
                if len(bits) % 2 != 0:
                    raise ValueError("odd bit count")
                out_bits: List[int] = []
                bit_index = 0
                for i in range(0, len(bits), 2):
                    t0, t1 = bits[i], bits[i + 1]
                    var_idx = (roll[bit_index % 32] >> (bit_index % 8)) & 1
                    recovered = self._recover_bit_variant(t0, t1, var_idx)
                    if recovered is None:
                        raise ValueError("invalid transition")
                    out_bits.append(recovered)
                    bit_index += 1
                payload = self._bits_to_bytes(out_bits)
                self._ratchet(b"")
                return payload
            except (ValueError, IndexError):
                continue

        self._restore(saved)
        return None

    def _recover_bit_variant(self, t0: int, t1: int, var_idx: int) -> Optional[int]:
        variant = self.variants[var_idx]
        for bit in (0, 1):
            if variant(bit) == (t0, t1):
                return bit
        return None

    @staticmethod
    def _pack_bits(bits: List[int]) -> bytes:
        out = bytearray()
        for i in range(0, len(bits), 8):
            byte = 0
            for j in range(8):
                if i + j < len(bits):
                    byte |= bits[i + j] << (7 - j)
            out.append(byte)
        return bytes(out)

    @staticmethod
    def _unpack_bits(data: bytes) -> List[int]:
        bits: List[int] = []
        for byte in data:
            for i in range(8):
                bits.append((byte >> (7 - i)) & 1)
        return bits

    @staticmethod
    def _bits_to_bytes(bits: List[int]) -> bytes:
        out = bytearray()
        for i in range(0, len(bits), 8):
            byte = 0
            for j in range(8):
                if i + j < len(bits):
                    byte |= bits[i + j] << (7 - j)
            out.append(byte)
        return bytes(out)