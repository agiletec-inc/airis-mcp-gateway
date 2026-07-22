"""AES-GCM based encryption utilities for credential storage."""

from __future__ import annotations

import os
import secrets
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class AESEncryption:
    """Symmetric encryption helper using AES-GCM."""

    _VALID_KEY_SIZES: Final[tuple[int, ...]] = (16, 24, 32)

    def __init__(self, hex_key: str | None):
        if not hex_key:
            raise RuntimeError("MASTER_KEY_HEX must be set for credential encryption")

        key_bytes: bytes | None = None
        try:
            key_bytes = bytes.fromhex(hex_key)
        except ValueError:
            # Fallback to urlsafe base64 (maintains compatibility with Fernet-style keys)
            try:
                import base64

                key_bytes = base64.urlsafe_b64decode(hex_key)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    "MASTER_KEY_HEX must be hex encoded or urlsafe base64"
                ) from exc

        if len(key_bytes) not in self._VALID_KEY_SIZES:
            raise RuntimeError(
                "MASTER_KEY_HEX length must be 128/192/256-bit (32/48/64 hex chars)"
            )

        self._key = key_bytes

    def encrypt(self, raw: bytes) -> bytes:
        aes = AESGCM(self._key)
        nonce = secrets.token_bytes(12)
        cipher_text = aes.encrypt(nonce, raw, associated_data=None)
        return nonce + cipher_text

    def decrypt(self, blob: bytes) -> bytes:
        if len(blob) < 13:
            raise ValueError("encrypted blob too short")
        nonce, cipher_text = blob[:12], blob[12:]
        aes = AESGCM(self._key)
        return aes.decrypt(nonce, cipher_text, associated_data=None)


def load_default_cipher() -> AESEncryption:
    """Construct the default cipher using environment configuration."""
    hex_key = os.getenv("MASTER_KEY_HEX") or os.getenv("ENCRYPTION_MASTER_KEY")
    return AESEncryption(hex_key)
