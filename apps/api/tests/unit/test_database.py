"""Tests for the database module (issue #85).

database.py selects one of three mode branches at import time, driven by
GATEWAY_MODE / DATABASE_URL env vars and SQLAlchemy availability. These
tests exercise each branch by reloading the module under controlled
conditions, always restoring the original lite-mode state afterward so
the rest of the suite is unaffected.
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest

import app.core.database as db_mod


@pytest.fixture
def reload_database():
    """Reload database.py with controlled env / SQLAlchemy availability.

    Yields a callable. On teardown it restores the original env vars,
    sys.modules entries, and reloads the module so other tests keep
    seeing the default lite-mode module.
    """
    env_keys = ("GATEWAY_MODE", "DATABASE_URL")
    saved_env = {key: os.environ.get(key) for key in env_keys}
    sa_modules = ("sqlalchemy", "sqlalchemy.ext.asyncio", "sqlalchemy.orm")
    saved_modules = {name: sys.modules.get(name) for name in sa_modules}

    def _reload(*, gateway_mode=None, database_url=None, block_sqlalchemy=False):
        for key, value in (("GATEWAY_MODE", gateway_mode), ("DATABASE_URL", database_url)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if block_sqlalchemy:
            # Setting a module to None in sys.modules makes `import` raise ImportError.
            for name in sa_modules:
                sys.modules[name] = None
        importlib.reload(db_mod)
        return db_mod

    yield _reload

    for name, module in saved_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    importlib.reload(db_mod)


async def _first_yield(async_gen):
    """Return the first value produced by an async generator, then close it."""
    try:
        return await async_gen.__anext__()
    finally:
        await async_gen.aclose()


@pytest.mark.asyncio
async def test_lite_mode_with_sqlalchemy(reload_database):
    """Lite mode: SQLAlchemy present but no DATABASE_URL — no engine, no sessions."""
    mod = reload_database(gateway_mode="lite", database_url=None)

    assert mod.is_db_available() is False
    assert mod.engine is None
    assert mod.AsyncSessionLocal is None
    assert await _first_yield(mod.get_db()) is None
    # Base is a real declarative base usable for model metadata.
    assert hasattr(mod.Base, "metadata")


@pytest.mark.asyncio
async def test_full_mode_creates_engine(reload_database):
    """Full mode: GATEWAY_MODE=full + DATABASE_URL builds a real engine and sessions."""
    mod = reload_database(
        gateway_mode="full",
        database_url="sqlite+aiosqlite:///:memory:",
    )

    assert mod.is_db_available() is True
    assert mod.engine is not None
    assert mod.AsyncSessionLocal is not None

    session = await _first_yield(mod.get_db())
    assert session is not None
    await mod.engine.dispose()


@pytest.mark.asyncio
async def test_full_mode_requires_database_url(reload_database):
    """GATEWAY_MODE=full without DATABASE_URL stays in lite mode."""
    mod = reload_database(gateway_mode="full", database_url=None)

    assert mod.is_db_available() is False
    assert mod.engine is None


@pytest.mark.asyncio
async def test_no_sqlalchemy_falls_back_to_stub_base(reload_database):
    """Without SQLAlchemy the module exposes a stub Base and no DB access."""
    mod = reload_database(block_sqlalchemy=True)

    assert mod.is_db_available() is False
    assert mod.engine is None
    assert mod.AsyncSessionLocal is None
    assert await _first_yield(mod.get_db()) is None
    # The stub Base is a plain class — it has no SQLAlchemy metadata.
    assert not hasattr(mod.Base, "metadata")
