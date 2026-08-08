# cogno/crypto/blake3_hash.py

class BLAKE3:
    """
    Pure-Python BLAKE3 — keyed hash mode for ADAP authentication.
    No external deps. Drop-in for HMAC.
    """

    CHUNK_SIZE = 1024  # bytes

    def __init__(self, key: bytes = None):
        if key:
            assert len(key) == 32, "BLAKE3 key must be 32 bytes"
            self.key_words = list(struct.unpack('<8I', key))
            self.flags_base = KEYED_HASH
        else:
            self.key_words = list(IV)
            self.flags_base = 0

        self.cv = self.key_words[:]
        self.chunk_counter = 0
        self.buf = b""

    def _process_chunk(self, chunk: bytes, flags: int) -> list[int]:
        """Process one 1024-byte chunk → chaining value."""
        cv = self.key_words[:]
        blocks = [chunk[i:i+64] for i in range(0, 1024, 64)]

        for i, block in enumerate(blocks):
            block_flags = self.flags_base | flags
            if i == 0:        block_flags |= CHUNK_START
            if i == 15:       block_flags |= CHUNK_END
            words = words_from_bytes(block)
            state = compress(cv, words, self.chunk_counter,
                             min(len(block), 64), block_flags)
            cv = state[:8]

        return cv

    def update(self, data: bytes) -> "BLAKE3":
        self.buf += data
        while len(self.buf) >= self.CHUNK_SIZE:
            chunk = self.buf[:self.CHUNK_SIZE]
            self.buf = self.buf[self.CHUNK_SIZE:]
            cv = self._process_chunk(chunk, 0)
            self.cv = cv
            self.chunk_counter += 1
        return self

    def digest(self, length: int = 32) -> bytes:
        """Finalize — output up to 2^64 bytes (extensible output)."""
        # Process remaining buffer as final chunk
        final = self.buf.ljust(self.CHUNK_SIZE, b'\x00')
        flags = CHUNK_START | CHUNK_END | ROOT | self.flags_base
        state = compress(
            self.key_words, words_from_bytes(final[:64]),
            self.chunk_counter, min(len(self.buf), 64), flags
        )
        output = bytes_from_words(state[:8])

        # Extend output if needed (XOF mode)
        while len(output) < length:
            state = compress(
                state[:8], words_from_bytes(final[:64]),
                self.chunk_counter + 1, 64, ROOT | self.flags_base
            )
            output += bytes_from_words(state[:8])

        return output[:length]

    def hexdigest(self, length: int = 32) -> str:
        return self.digest(length).hex()# test: cogno/crypto/__main__.py

from cogno.crypto.arx import IV, g, compress, words_from_bytes
from cogno.crypto.xor_diffusion import XORDiffusion
from cogno.crypto.blake3_hash import BLAKE3
from cogno.core.bitstate import BitState

# ── 1. Hash a node state with BLAKE3 ──────────────────────────
node_data = b"quantum_node:threat:0.87:ts:1742000000"
h = BLAKE3(key=b"adap_cogno_key_00" + b'\x00' * 15)
h.update(node_data)
print("BLAKE3 digest:", h.hexdigest())

# ── 2. XOR diffuse a BitState register ────────────────────────
bs = BitState(64)
bs.superpose(3, 7, 12, 45, weights=[0.6, 0.2, 0.1, 0.1])

diff = XORDiffusion(key=b"cogno_arx_v1")
diffused = diff.diffuse_bits(bs.register)
print(f"Original : {bs.register:064b}")
print(f"Diffused : {diffused:064b}")
print(f"Hamming  : {bin(bs.register ^ diffused).count('1')} bits changed")

# ── 3. Avalanche test ─────────────────────────────────────────
rate = diff.avalanche_test(node_data)
print(f"Avalanche: {rate:.2%}")   # should be ~50%

# ── 4. Encrypt/decrypt node state ─────────────────────────────
encrypted = diff.xor_encrypt(node_data)
decrypted = diff.xor_decrypt(encrypted)
assert decrypted == node_data
print("XOR encrypt/decrypt: ✓")