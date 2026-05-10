"""Tests for production fail-closed behavior in EncryptionManager (issues #93, #113)."""
from __future__ import annotations

import os
import stat

import pytest

from app.core.encryption import EncryptionManager


@pytest.fixture
def isolated_key_dir(tmp_path, monkeypatch):
    key_file = tmp_path / "encryption_master.key"
    monkeypatch.setenv("ENCRYPTION_MASTER_KEY_FILE", str(key_file))
    for key in ("ENCRYPTION_MASTER_KEY", "ENV", "ENCRYPTION_ALLOW_INSECURE_KEY_PERMS"):
        monkeypatch.delenv(key, raising=False)
    yield tmp_path


def test_production_without_env_var_raises_even_if_file_exists(
    isolated_key_dir, monkeypatch
):
    key_file = isolated_key_dir / "encryption_master.key"
    key_file.write_text("some-leftover-key")
    os.chmod(key_file, 0o600)

    monkeypatch.setenv("ENV", "production")

    with pytest.raises(RuntimeError, match="ENCRYPTION_MASTER_KEY must be set"):
        EncryptionManager()


def test_production_with_env_var_succeeds(isolated_key_dir, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ENCRYPTION_MASTER_KEY", "production-key")

    manager = EncryptionManager()

    ciphertext = manager.encrypt("hello")
    assert manager.decrypt(ciphertext) == "hello"


def test_development_auto_generates_and_chmods_key(isolated_key_dir):
    manager = EncryptionManager()
    key_file = isolated_key_dir / "encryption_master.key"
    salt_file = isolated_key_dir / "encryption_salt.bin"

    assert key_file.is_file()
    assert salt_file.is_file()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(salt_file.stat().st_mode) == 0o600

    assert manager.decrypt(manager.encrypt("roundtrip")) == "roundtrip"


def test_insecure_perms_override_is_respected(isolated_key_dir, monkeypatch):
    import app.core.encryption as enc

    real_chmod = os.chmod

    def fake_chmod(path, mode):
        # Simulate a filesystem where chmod is a no-op.
        real_chmod(path, 0o644)

    monkeypatch.setattr(enc.os, "chmod", fake_chmod)

    monkeypatch.setenv("ENCRYPTION_ALLOW_INSECURE_KEY_PERMS", "1")
    manager = EncryptionManager()
    assert manager.decrypt(manager.encrypt("ok")) == "ok"


def test_insecure_perms_fail_closed_by_default(isolated_key_dir, monkeypatch):
    import app.core.encryption as enc

    real_chmod = os.chmod

    def fake_chmod(path, mode):
        real_chmod(path, 0o644)

    monkeypatch.setattr(enc.os, "chmod", fake_chmod)

    with pytest.raises(RuntimeError, match="insecure permissions"):
        EncryptionManager()
