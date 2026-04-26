"""Tests for ENV=production fail-closed validation (issue #97)."""
from __future__ import annotations

import importlib

import pytest

from app.core import config as config_module


@pytest.fixture
def clean_env(monkeypatch):
    for key in ("AIRIS_API_KEY", "ALLOWED_ORIGINS", "ENV"):
        monkeypatch.delenv(key, raising=False)
    yield monkeypatch
    # Restore the module to its pristine state so later test files (which
    # may also importlib.reload this module) see defaults rather than
    # whatever ENV we injected here. monkeypatch undoes its own env changes
    # in LIFO order *after* fixture teardown runs, so explicitly scrub the
    # relevant variables before reloading.
    import os as _os
    for key in ("AIRIS_API_KEY", "ALLOWED_ORIGINS", "ENV"):
        _os.environ.pop(key, None)
    importlib.reload(config_module)


def _reload_config():
    """Reload config module so Settings() re-reads os.environ.

    Other tests in this suite (test_config.py) also call importlib.reload on
    the same module, so we must always re-read the freshly-reloaded exception
    class rather than caching it at import time.
    """
    reloaded = importlib.reload(config_module)
    return reloaded


def _reload_settings():
    mod = _reload_config()
    return mod.settings, mod.InsecureProductionConfig, mod.validate_environment


def test_development_without_api_key_returns_warnings(clean_env):
    clean_env.setenv("ENV", "development")
    clean_env.setenv("ALLOWED_ORIGINS", "https://app.example.com")
    _settings, _exc_cls, validate = _reload_settings()

    warnings = validate()

    assert any("AIRIS_API_KEY" in w for w in warnings)


def test_production_without_api_key_raises(clean_env):
    clean_env.setenv("ENV", "production")
    clean_env.setenv("ALLOWED_ORIGINS", "https://app.example.com")
    _settings, exc_cls, validate = _reload_settings()

    with pytest.raises(exc_cls) as exc:
        validate()
    assert "AIRIS_API_KEY" in str(exc.value)


def test_production_without_allowed_origins_raises(clean_env):
    clean_env.setenv("ENV", "production")
    clean_env.setenv("AIRIS_API_KEY", "secret")
    _settings, exc_cls, validate = _reload_settings()

    with pytest.raises(exc_cls) as exc:
        validate()
    assert "ALLOWED_ORIGINS" in str(exc.value)


def test_production_wildcard_origins_raises(clean_env):
    clean_env.setenv("ENV", "production")
    clean_env.setenv("AIRIS_API_KEY", "secret")
    clean_env.setenv("ALLOWED_ORIGINS", "*")
    _settings, exc_cls, validate = _reload_settings()

    with pytest.raises(exc_cls) as exc:
        validate()
    assert "ALLOWED_ORIGINS" in str(exc.value)


def test_production_with_both_set_passes(clean_env):
    clean_env.setenv("ENV", "production")
    clean_env.setenv("AIRIS_API_KEY", "secret")
    clean_env.setenv("ALLOWED_ORIGINS", "https://app.example.com")
    _settings, _exc_cls, validate = _reload_settings()

    warnings = validate()

    assert not any("AIRIS_API_KEY" in w for w in warnings)
    assert not any("ALLOWED_ORIGINS" in w for w in warnings)


def test_production_reports_both_errors_at_once(clean_env):
    clean_env.setenv("ENV", "production")
    _settings, exc_cls, validate = _reload_settings()

    with pytest.raises(exc_cls) as exc:
        validate()
    message = str(exc.value)
    assert "AIRIS_API_KEY" in message
    assert "ALLOWED_ORIGINS" in message
