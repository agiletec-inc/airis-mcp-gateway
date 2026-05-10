"""Tests for _env_int/_env_float helpers (issue #107).

These tests always look up the helpers via the live module because
test_config.py and test_config_production.py may `importlib.reload` the
config module between test files. Holding references imported at the top
of this module would leave them pointing at a stale InvalidEnvVar class
that the live module no longer raises.
"""
from __future__ import annotations

import pytest

from app.core import config as config_module


def _helpers():
    return (
        config_module.InvalidEnvVar,
        config_module._env_int,
        config_module._env_float,
    )


def test_env_int_returns_default_when_missing(monkeypatch):
    _, env_int, _ = _helpers()
    monkeypatch.delenv("SOME_INT", raising=False)
    assert env_int("SOME_INT", 42) == 42


def test_env_int_returns_default_when_empty(monkeypatch):
    _, env_int, _ = _helpers()
    monkeypatch.setenv("SOME_INT", "")
    assert env_int("SOME_INT", 7) == 7


def test_env_int_parses_value(monkeypatch):
    _, env_int, _ = _helpers()
    monkeypatch.setenv("SOME_INT", "99")
    assert env_int("SOME_INT", 0) == 99


def test_env_int_raises_on_garbage(monkeypatch):
    invalid_cls, env_int, _ = _helpers()
    monkeypatch.setenv("SOME_INT", "not-a-number")
    with pytest.raises(invalid_cls, match="SOME_INT"):
        env_int("SOME_INT", 0)


def test_env_float_parses_value(monkeypatch):
    _, _, env_float = _helpers()
    monkeypatch.setenv("SOME_FLOAT", "1.5")
    assert env_float("SOME_FLOAT", 0.0) == 1.5


def test_env_float_raises_on_garbage(monkeypatch):
    invalid_cls, _, env_float = _helpers()
    monkeypatch.setenv("SOME_FLOAT", "abc")
    with pytest.raises(invalid_cls, match="SOME_FLOAT"):
        env_float("SOME_FLOAT", 0.0)


def test_env_float_returns_default_when_missing(monkeypatch):
    _, _, env_float = _helpers()
    monkeypatch.delenv("SOME_FLOAT", raising=False)
    assert env_float("SOME_FLOAT", 9.0) == 9.0
