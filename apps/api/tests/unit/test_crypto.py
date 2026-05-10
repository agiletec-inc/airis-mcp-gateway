"""Tests for AESEncryption (issue #85)."""
from __future__ import annotations

import base64
import os
import secrets

import pytest

from app.core.crypto import AESEncryption, load_default_cipher


def _hex_key(size: int) -> str:
    return secrets.token_bytes(size).hex()


def test_rejects_empty_key():
    with pytest.raises(RuntimeError, match="MASTER_KEY_HEX must be set"):
        AESEncryption("")


def test_rejects_none_key():
    with pytest.raises(RuntimeError, match="MASTER_KEY_HEX must be set"):
        AESEncryption(None)


def test_rejects_invalid_encoding():
    with pytest.raises(RuntimeError, match="hex encoded or urlsafe base64"):
        AESEncryption("!!! not hex !!!")


@pytest.mark.parametrize("size", [16, 24, 32])
def test_accepts_valid_hex_key_sizes(size):
    cipher = AESEncryption(_hex_key(size))
    encrypted = cipher.encrypt(b"hello")
    assert cipher.decrypt(encrypted) == b"hello"


def test_rejects_wrong_key_size():
    with pytest.raises(RuntimeError, match="128/192/256-bit"):
        AESEncryption(secrets.token_bytes(20).hex())


def test_accepts_urlsafe_base64_key():
    raw = secrets.token_bytes(32)
    b64 = base64.urlsafe_b64encode(raw).decode()
    cipher = AESEncryption(b64)
    assert cipher.decrypt(cipher.encrypt(b"roundtrip")) == b"roundtrip"


def test_encrypt_produces_distinct_nonces():
    cipher = AESEncryption(_hex_key(32))
    a = cipher.encrypt(b"same plaintext")
    b = cipher.encrypt(b"same plaintext")
    assert a != b  # Different nonce → different ciphertext


def test_decrypt_rejects_truncated_blob():
    cipher = AESEncryption(_hex_key(32))
    with pytest.raises(ValueError, match="too short"):
        cipher.decrypt(b"\x00" * 5)


def test_decrypt_detects_tamper():
    cipher = AESEncryption(_hex_key(32))
    blob = cipher.encrypt(b"do not tamper")
    tampered = blob[:-1] + bytes([blob[-1] ^ 0xFF])
    with pytest.raises(Exception):
        cipher.decrypt(tampered)


def test_load_default_cipher_prefers_master_key_hex(monkeypatch):
    key = _hex_key(32)
    monkeypatch.setenv("MASTER_KEY_HEX", key)
    monkeypatch.delenv("ENCRYPTION_MASTER_KEY", raising=False)
    cipher = load_default_cipher()
    assert cipher.decrypt(cipher.encrypt(b"env")) == b"env"


def test_load_default_cipher_falls_back_to_encryption_master_key(monkeypatch):
    monkeypatch.delenv("MASTER_KEY_HEX", raising=False)
    monkeypatch.setenv("ENCRYPTION_MASTER_KEY", _hex_key(32))
    cipher = load_default_cipher()
    assert cipher.decrypt(cipher.encrypt(b"fallback")) == b"fallback"


def test_load_default_cipher_raises_without_either_env(monkeypatch):
    monkeypatch.delenv("MASTER_KEY_HEX", raising=False)
    monkeypatch.delenv("ENCRYPTION_MASTER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MASTER_KEY_HEX must be set"):
        load_default_cipher()
