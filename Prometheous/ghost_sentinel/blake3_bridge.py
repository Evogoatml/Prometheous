"""
BLAKE3 bridge — prefers native ``blake3`` wheel, falls back to keyed BLAKE2b.
"""
from __future__ import annotations

import hashlib
from typing import Optional

_HAS_BLAKE3 = False

try:
    import blake3 as _blake3  # type: ignore[import-untyped]

    _HAS_BLAKE3 = True
except ImportError:
    _blake3 = None


def hash_bytes(data: bytes, key: Optional[bytes] = None, length: int = 32) -> bytes:
    """Keyed or unkeyed 32-byte digest."""
    if _HAS_BLAKE3 and _blake3 is not None:
        if key:
            return _blake3.blake3(data, key=key[:32].ljust(32, b"\x00")).digest(length)
        return _blake3.blake3(data).digest(length)

    if key:
        return hashlib.blake2b(data, digest_size=length, key=key[:32].ljust(32, b"\x00")).digest()
    return hashlib.blake2b(data, digest_size=length).digest()


def ratchet(state: bytes, extra: bytes = b"", counter: int = 0, length: int = 32) -> bytes:
    material = state + extra + counter.to_bytes(8, "big")
    return hash_bytes(material, key=state[:32].ljust(32, b"\x00"), length=length)


def mac(payload: bytes, key_material: bytes, length: int = 16) -> bytes:
    return hash_bytes(payload + key_material[:16], key=key_material[:32].ljust(32, b"\x00"), length=length)


def backend_name() -> str:
    return "blake3" if _HAS_BLAKE3 else "blake2b-fallback"