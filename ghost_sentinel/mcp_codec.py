"""
Manchester Cryptographic Protocol (MCP) codec.

Protects serialized CRDT deltas with polymorphic Manchester encoding,
rolling ratchet state, sequence numbers, and keyed MAC.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ghost_sentinel.crypto_seed import mac_payload
from ghost_sentinel.rolling_manchester import RollingManchester

MAC_SIZE = 16
HEADER_SIZE = 4 + MAC_SIZE + 8  # length + mac + seq


@dataclass
class MCPConfig:
    """security_level: 0=off, 1=rolling, 2=aggressive polymorphic."""
    security_level: int = 1
    max_roll_window: int = 2


class MCPCodec:
    """Adaptive rolling polymorphic encoder for CRDT payloads."""

    def __init__(self, seed: bytes, config: MCPConfig | None = None):
        self.rm = RollingManchester(seed)
        self.config = config or MCPConfig()
        self._seq = 0

    def protect(self, payload: bytes) -> bytes:
        if self.config.security_level == 0:
            return payload

        xor_key = self.rm._peek_ratchet(b"")[0]
        encoded = self.rm.encode(payload)
        if self.config.security_level >= 2:
            encoded = bytes(b ^ xor_key for b in encoded)

        mac = mac_payload(payload, self.rm.state, length=MAC_SIZE)
        length = len(encoded).to_bytes(4, "big")
        seq = self._seq.to_bytes(8, "big")
        self._seq += 1
        return length + mac + seq + encoded

    def recover(self, wire: bytes) -> Optional[bytes]:
        if self.config.security_level == 0:
            return wire
        if len(wire) < HEADER_SIZE:
            return None

        length = int.from_bytes(wire[:4], "big")
        mac = wire[4:4 + MAC_SIZE]
        seq = int.from_bytes(wire[4 + MAC_SIZE:HEADER_SIZE], "big")
        encoded = wire[HEADER_SIZE:HEADER_SIZE + length]
        if len(encoded) != length:
            return None

        xor_key = self.rm._peek_ratchet(b"")[0]
        if self.config.security_level >= 2:
            encoded = bytes(b ^ xor_key for b in encoded)

        payload = self.rm.decode(encoded, window=self.config.max_roll_window)
        if payload is None:
            return None

        expected_mac = mac_payload(payload, self.rm.state, length=MAC_SIZE)
        if mac != expected_mac:
            return None

        if seq < self._seq:
            return None  # anti-replay: reject old sequence

        self._seq = seq + 1
        return payload