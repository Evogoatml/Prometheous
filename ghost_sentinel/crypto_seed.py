"""
Cryptographic seed derivation for Ghost Sentinel.

Uses Argon2id (AXR-style KDF) when available, with a safe fallback for
environments where OpenSSL Argon2 is not compiled in.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from ghost_sentinel.blake3_bridge import backend_name, hash_bytes, mac as _mac, ratchet as _ratchet

try:
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
except ImportError:  # pragma: no cover
    Argon2id = None  # type: ignore[misc, assignment]


def _argon2id_derive(
    secret: bytes,
    salt: bytes,
    length: int = 32,
    *,
    time_cost: int = 3,
    memory_cost_kib: int = 65536,
    parallelism: int = 4,
) -> bytes:
    if Argon2id is None:
        raise RuntimeError("Argon2id unavailable")
    kdf = Argon2id(
        salt=salt,
        length=length,
        iterations=time_cost,
        lanes=parallelism,
        memory_cost=memory_cost_kib,
    )
    return kdf.derive(secret)


def _fallback_derive(secret: bytes, salt: bytes, length: int = 32) -> bytes:
    """PBKDF2 fallback when Argon2id is unavailable."""
    return hashlib.pbkdf2_hmac("sha256", secret, salt, 200_000, dklen=length)


def derive_swarm_seed(
    master_secret: Optional[bytes] = None,
    *,
    swarm_id: str = "ghost-sentinel",
    context: str = "mcp-v1",
    length: int = 32,
) -> bytes:
    """
    Derive a per-swarm 32-byte seed from a master secret.

    Priority:
      1. ``GHOST_SENTINEL_MASTER_SECRET`` env (hex or utf-8)
      2. ``master_secret`` argument
      3. Ephemeral random (dev only — logs warning via caller)
    """
    if master_secret is None:
        env = os.getenv("GHOST_SENTINEL_MASTER_SECRET", "")
        if env:
            try:
                master_secret = bytes.fromhex(env)
            except ValueError:
                master_secret = env.encode("utf-8")
        else:
            master_secret = os.urandom(32)

    salt = hash_bytes(f"{swarm_id}:{context}".encode(), length=16)

    try:
        return _argon2id_derive(master_secret, salt, length=length)
    except Exception:
        return _fallback_derive(master_secret, salt, length=length)


def blake3_ratchet(state: bytes, extra: bytes = b"", counter: int = 0) -> bytes:
    """BLAKE3 ratchet (native when available, BLAKE2b fallback)."""
    return _ratchet(state, extra, counter)


def mac_payload(payload: bytes, key_material: bytes, length: int = 16) -> bytes:
    """Keyed MAC for MCP framing."""
    return _mac(payload, key_material, length)


def crypto_backend() -> str:
    return backend_name()