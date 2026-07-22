"""Tests for dashboard summary aggregation."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.api.endpoints.mcp_config import MCPServerInfo
from app.core.database import Base
from app.services.dashboard_summary import build_dashboard_summary
from app.crud import secret as secret_crud
from app.crud import mcp_server_state as state_crud

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_db():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_summary_counts(monkeypatch, test_db: AsyncSession):
    servers = [
        MCPServerInfo(
            id="tavily",
            name="Tavily",
            description="Search",
            category="auth-required",
            apiKeyRequired=True,
            recommended=True,
            builtin=False,
            enabled=False,
            command="npx",
            args=["tavily"],
            env=None,
        ),
        MCPServerInfo(
            id="filesystem",
            name="Filesystem",
            description="Files",
            category="gateway",
            apiKeyRequired=False,
            recommended=True,
            builtin=False,
            enabled=False,
            command="npx",
            args=["fs"],
            env=None,
        ),
    ]

    monkeypatch.setattr(
        "app.services.dashboard_summary.load_mcp_servers_from_config",
        lambda: servers,
    )

    await state_crud.upsert_server_state(test_db, "tavily", True)
    await secret_crud.create_secret(test_db, "tavily", "TAVILY_API_KEY", "tvly-key")

    summary = await build_dashboard_summary(test_db)

    assert summary.stats.total == 2
    assert summary.stats.active == 1
    assert summary.stats.inactive == 1
    assert summary.stats.api_key_missing == 0

    tavily = next(server for server in summary.servers if server.id == "tavily")
    filesystem = next(server for server in summary.servers if server.id == "filesystem")

    assert tavily.enabled is True
    assert tavily.api_key_configured is True
    assert filesystem.enabled is False
    assert filesystem.api_key_configured is False
