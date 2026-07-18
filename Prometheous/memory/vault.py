import base64
import json
import os
import secrets
from typing import Any, Optional
from utils.config import cfg

class EncryptedVault:
    def __init__(self, vault_dir: Optional[str] = None):
        self._vault_dir = vault_dir or cfg.VAULT_DIR
        self._key_path = os.path.join(self._vault_dir, ".vault.key")
        self._data_path = os.path.join(self._vault_dir, "vault.enc")
        os.makedirs(self._vault_dir, exist_ok=True)

    def _load_or_create_key(self) -> bytes:
        if os.path.exists(self._key_path):
            with open(self._key_path, "rb") as f:
                return f.read()
        key = secrets.token_bytes(32)
        with open(self._key_path, "wb") as f:
            f.write(key)
        try:
            os.chmod(self._key_path, 0o600)
        except OSError:
            pass
        return key

    def store(self, obj: Any) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = self._load_or_create_key()
        data = json.dumps(obj).encode()
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, data, None)

        envelope = {
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }
        with open(self._data_path, "w") as f:
            json.dump(envelope, f)

    def load(self) -> Any:
        if not os.path.exists(self._data_path):
            return {}
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = self._load_or_create_key()
        with open(self._data_path) as f:
            envelope = json.load(f)
        nonce = base64.b64decode(envelope["nonce"])
        ciphertext = base64.b64decode(envelope["ciphertext"])
        aesgcm = AESGCM(key)
        data = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(data.decode())

    def get(self, key: str, default: Any = None) -> Any:
        vault = self.load()
        return vault.get(key, default)

    def set(self, key: str, value: Any) -> None:
        vault = self.load()
        vault[key] = value
        self.store(vault)

    def append(self, key: str, entry: Any) -> int:
        vault = self.load()
        vault.setdefault(key, []).append(entry)
        self.store(vault)
        return len(vault[key]) - 1
