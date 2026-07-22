"""
Tests for encryption module.
"""

import os
import pytest
from unittest.mock import patch


def test_encrypt_decrypt_roundtrip():
    """Test that encryption and decryption produce original value."""
    from app.core.encryption import EncryptionManager

    manager = EncryptionManager(master_key="test-master-key-12345")

    plaintext = "secret-api-key-value"
    encrypted = manager.encrypt(plaintext)

    assert encrypted != plaintext.encode()
    assert manager.decrypt(encrypted) == plaintext


def test_encrypt_different_plaintexts_produce_different_ciphertexts():
    """Test that different plaintexts produce different ciphertexts."""
    from app.core.encryption import EncryptionManager

    manager = EncryptionManager(master_key="test-master-key-12345")

    encrypted1 = manager.encrypt("secret1")
    encrypted2 = manager.encrypt("secret2")

    assert encrypted1 != encrypted2


def test_same_plaintext_produces_different_ciphertexts():
    """Test that same plaintext produces different ciphertexts (due to IV)."""
    from app.core.encryption import EncryptionManager

    manager = EncryptionManager(master_key="test-master-key-12345")

    plaintext = "same-secret"
    encrypted1 = manager.encrypt(plaintext)
    encrypted2 = manager.encrypt(plaintext)

    # Fernet uses random IV, so same plaintext produces different ciphertext
    assert encrypted1 != encrypted2
    # But both decrypt to the same value
    assert manager.decrypt(encrypted1) == plaintext
    assert manager.decrypt(encrypted2) == plaintext


def test_different_master_keys_produce_different_results():
    """Test that different master keys produce different encryption results."""
    from app.core.encryption import EncryptionManager

    manager1 = EncryptionManager(master_key="key-one-12345")
    manager2 = EncryptionManager(master_key="key-two-67890")

    plaintext = "same-secret"
    encrypted1 = manager1.encrypt(plaintext)
    encrypted2 = manager2.encrypt(plaintext)

    # Different keys should produce different results
    assert encrypted1 != encrypted2

    # Decryption with wrong key should fail
    with pytest.raises(Exception):
        manager2.decrypt(encrypted1)


def test_generate_master_key():
    """Test master key generation."""
    from app.core.encryption import EncryptionManager

    key1 = EncryptionManager.generate_master_key()
    key2 = EncryptionManager.generate_master_key()

    assert key1 != key2
    assert len(key1) > 20  # Fernet keys are base64 encoded


def test_encrypt_empty_string():
    """Test encrypting empty string."""
    from app.core.encryption import EncryptionManager

    manager = EncryptionManager(master_key="test-master-key-12345")

    encrypted = manager.encrypt("")
    assert manager.decrypt(encrypted) == ""


def test_encrypt_unicode():
    """Test encrypting unicode strings."""
    from app.core.encryption import EncryptionManager

    manager = EncryptionManager(master_key="test-master-key-12345")

    plaintext = "秘密のキー 🔐"
    encrypted = manager.encrypt(plaintext)
    assert manager.decrypt(encrypted) == plaintext


def test_decrypt_invalid_data_raises():
    """Test that decrypting invalid data raises an exception."""
    from app.core.encryption import EncryptionManager

    manager = EncryptionManager(master_key="test-master-key-12345")

    with pytest.raises(Exception):
        manager.decrypt(b"invalid-encrypted-data")


def test_manager_uses_env_var_key():
    """Test that manager uses ENCRYPTION_MASTER_KEY env var if set."""
    from importlib import reload

    env_key = "env-var-master-key-12345"

    with patch.dict(os.environ, {"ENCRYPTION_MASTER_KEY": env_key}):
        # Need to reload to pick up env var
        from app.core import encryption

        reload(encryption)

        manager = encryption.EncryptionManager()
        assert manager.master_key == env_key
