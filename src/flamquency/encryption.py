"""Password-based encryption for FlamQuency-Sync blob storage.

Blobs are encrypted with Fernet (AES-128-CBC + HMAC-SHA256, authenticated).
The Fernet key is derived from the user's password with PBKDF2-HMAC-SHA256
using a random per-store salt. Only the salt, iteration count and a small
verifier token are persisted — never the password and never the key itself.

Layout of the key file (<store>/encryption.json)::

    {
      "version": 1,
      "kdf": "pbkdf2-sha256",
      "salt": "<hex>",
      "iterations": 480000,
      "verifier": "<fernet token of a known constant>"
    }

The verifier is what makes a wrong password fail loudly instead of
producing garbage on decryption.
"""
import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

KEY_FILENAME = "encryption.json"
KEY_VERSION = 1
DEFAULT_ITERATIONS = 480_000
SALT_BYTES = 16
VERIFIER_PLAINTEXT = b"flamquency-blob-store-verifier-v1"


class EncryptionError(Exception):
    """Base class for all encryption failures."""


class WrongPasswordError(EncryptionError):
    """The supplied password does not match the store's key file."""


class EncryptionLockedError(EncryptionError):
    """The store is encrypted but no unlocked key is available."""


class DecryptionError(EncryptionError):
    """Ciphertext could not be decrypted (wrong key or corrupted data)."""


def _derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    """Derive a 32-byte urlsafe-base64 Fernet key from a password."""
    if not isinstance(password, str) or not password:
        raise EncryptionError("Password must be a non-empty string")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


class EncryptionManager:
    """Holds (or derives) the store key and encrypts/decrypts payloads.

    Usage::

        mgr = EncryptionManager.enable(store_dir, "my password")
        token = mgr.encrypt(b"data")

        mgr = EncryptionManager(store_dir)   # locked until unlocked
        mgr.unlock("my password")
        data = mgr.decrypt(token)
    """

    def __init__(self, base_path, iterations=None):
        self.base_path = Path(base_path)
        self.key_path = self.base_path / KEY_FILENAME
        self.iterations = iterations
        self._fernet = None
        self._meta = self._load_meta()

    # ── construction ──────────────────────────────────────────

    @classmethod
    def enable(cls, base_path, password, iterations=DEFAULT_ITERATIONS):
        """Create a key file for a new encrypted store and return it unlocked."""
        mgr = cls(base_path, iterations=iterations)
        if mgr.is_configured:
            raise EncryptionError(
                f"Encryption is already configured at {mgr.key_path}"
            )
        mgr._write_key_file(password, iterations)
        mgr._meta = mgr._load_meta()
        mgr.unlock(password)
        return mgr

    def _load_meta(self):
        if not self.key_path.exists():
            return None
        try:
            meta = json.loads(self.key_path.read_text())
        except Exception:
            raise EncryptionError(f"Corrupt encryption key file: {self.key_path}")
        if meta.get("version") != KEY_VERSION:
            raise EncryptionError(
                f"Unsupported key file version: {meta.get('version')!r}"
            )
        if self.iterations is None:
            self.iterations = meta.get("iterations", DEFAULT_ITERATIONS)
        return meta

    def _write_key_file(self, password, iterations):
        salt = os.urandom(SALT_BYTES)
        fernet = Fernet(_derive_key(password, salt, iterations))
        meta = {
            "version": KEY_VERSION,
            "kdf": "pbkdf2-sha256",
            "salt": salt.hex(),
            "iterations": iterations,
            "verifier": fernet.encrypt(VERIFIER_PLAINTEXT).decode("ascii"),
        }
        self.base_path.mkdir(parents=True, exist_ok=True)
        tmp = self.key_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.key_path)

    # ── state ─────────────────────────────────────────────────

    @property
    def is_configured(self):
        """True when a key file exists for this store."""
        return self._meta is not None

    @property
    def is_unlocked(self):
        """True when an in-memory key is available."""
        return self._fernet is not None

    # ── lifecycle ─────────────────────────────────────────────

    def unlock(self, password):
        """Derive the key from *password* and verify it against the key file."""
        meta = self._meta
        if meta is None:
            raise EncryptionError("Encryption is not configured for this store")
        iterations = meta.get("iterations", self.iterations or DEFAULT_ITERATIONS)
        salt = bytes.fromhex(meta["salt"])
        fernet = Fernet(_derive_key(password, salt, iterations))
        try:
            verifier = fernet.decrypt(meta["verifier"].encode("ascii"))
        except InvalidToken:
            raise WrongPasswordError("Wrong password for encrypted blob store")
        if verifier != VERIFIER_PLAINTEXT:
            raise WrongPasswordError("Wrong password for encrypted blob store")
        self._fernet = fernet
        self.iterations = iterations
        return True

    def lock(self):
        """Drop the in-memory key."""
        self._fernet = None

    def disable(self):
        """Remove the key file and forget the key (blobs must be decrypted first)."""
        if self.key_path.exists():
            self.key_path.unlink()
        self._fernet = None
        self._meta = None

    def change_password(self, new_password, iterations=None):
        """Write a NEW key file and return a fresh unlocked manager.

        Existing blobs stay encrypted with the old key — call
        ``BlobStore.rekey(old_mgr, new_mgr)`` afterwards to re-encrypt them.
        """
        if not self.is_unlocked:
            raise EncryptionLockedError("Store must be unlocked to change password")
        iterations = iterations or self.iterations or DEFAULT_ITERATIONS
        self._write_key_file(new_password, iterations)
        new_mgr = EncryptionManager(self.base_path, iterations=iterations)
        new_mgr.unlock(new_password)
        return new_mgr

    # ── crypto ────────────────────────────────────────────────

    def encrypt(self, data: bytes) -> bytes:
        if self._fernet is None:
            raise EncryptionLockedError("Blob store is encrypted but locked")
        return self._fernet.encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        if self._fernet is None:
            raise EncryptionLockedError("Blob store is encrypted but locked")
        try:
            return self._fernet.decrypt(token)
        except InvalidToken:
            raise DecryptionError(
                "Failed to decrypt blob — wrong key or corrupted data"
            )
