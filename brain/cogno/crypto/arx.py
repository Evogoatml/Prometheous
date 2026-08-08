# cogno/crypto/arx.py
import struct
import numpy as np
from ctypes import c_uint32

# ── Constants ──────────────────────────────────────────────────
# BLAKE3 uses these IV constants (first 8 primes' square roots)
IV = [
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
]

# BLAKE3 message schedule permutation
MSG_PERMUTATION = [2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8]

# ── ARX Primitives ─────────────────────────────────────────────
def add32(a: int, b: int) -> int:
    """Add mod 2^32 — wraps cleanly, no overflow exceptions."""
    return (a + b) & 0xFFFFFFFF

def rotr32(x: int, n: int) -> int:
    """Rotate right 32-bit — bitwise circular shift."""
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF

def rotl32(x: int, n: int) -> int:
    """Rotate left 32-bit."""
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

def xor32(a: int, b: int) -> int:
    """XOR — the heart of diffusion."""
    return a ^ b

# ── BLAKE3 G Function (quarter round) ──────────────────────────
def g(state: list[int], a: int, b: int, c: int, d: int,
      mx: int, my: int) -> None:
    """
    The G mixing function — 4 ARX operations per call.
    Mixes two message words (mx, my) into 4 state words.
    Mutates state in place.

    Round structure:
      a = (a + b + mx)    ADD
      d = rotr(d ^ a, 16) XOR + ROTATE
      c = (c + d)         ADD
      b = rotr(b ^ c, 12) XOR + ROTATE
      a = (a + b + my)    ADD
      d = rotr(d ^ a, 8)  XOR + ROTATE
      c = (c + d)         ADD
      b = rotr(b ^ c, 7)  XOR + ROTATE
    """
    state[a] = add32(add32(state[a], state[b]), mx)
    state[d] = rotr32(xor32(state[d], state[a]), 16)
    state[c] = add32(state[c], state[d])
    state[b] = rotr32(xor32(state[b], state[c]), 12)
    state[a] = add32(add32(state[a], state[b]), my)
    state[d] = rotr32(xor32(state[d], state[a]),  8)
    state[c] = add32(state[c], state[d])
    state[b] = rotr32(xor32(state[b], state[c]),  7)