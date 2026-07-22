"""Unit tests for MCP server state CRUD operations"""

import pytest
import pytest_asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.crud import mcp_server_state as crud
from app.core.database import Base
from app.crud import mcp_server as server_crud
from app.schemas.mcp_server import MCPServerCreate


# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_db():
    """Create test database session"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session

    # Drop tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_server_state(test_db: AsyncSession):
    """Test creating a new server state"""
    # Create
    state = await crud.create_server_state(test_db, "test-server", True)

    # Verify
    assert state.server_id == "test-server"
    assert state.enabled is True
    assert state.id is not None
    assert isinstance(state.created_at, datetime)
    assert isinstance(state.updated_at, datetime)


@pytest.mark.asyncio
async def test_get_server_state(test_db: AsyncSession):
    """Test retrieving a server state"""
    # Create
    await crud.create_server_state(test_db, "test-server", True)

    # Retrieve
    state = await crud.get_server_state(test_db, "test-server")

    # Verify
    assert state is not None
    assert state.server_id == "test-server"
    assert state.enabled is True


@pytest.mark.asyncio
async def test_get_server_state_not_found(test_db: AsyncSession):
    """Test retrieving a non-existent server state"""
    state = await crud.get_server_state(test_db, "non-existent")
    assert state is None


@pytest.mark.asyncio
async def test_update_server_state(test_db: AsyncSession):
    """Test updating a server state"""
    # Create
    await crud.create_server_state(test_db, "test-server", True)

    # Update
    updated = await crud.update_server_state(test_db, "test-server", False)

    # Verify
    assert updated is not None
    assert updated.server_id == "test-server"
    assert updated.enabled is False


@pytest.mark.asyncio
async def test_update_server_state_not_found(test_db: AsyncSession):
    """Test updating a non-existent server state"""
    result = await crud.update_server_state(test_db, "non-existent", True)
    assert result is None


@pytest.mark.asyncio
async def test_upsert_server_state_create(test_db: AsyncSession):
    """Test upsert creates new state when not exists"""
    # Upsert (should create)
    state = await crud.upsert_server_state(test_db, "new-server", True)

    # Verify
    assert state.server_id == "new-server"
    assert state.enabled is True


@pytest.mark.asyncio
async def test_upsert_server_state_update(test_db: AsyncSession):
    """Test upsert updates existing state"""
    # Create
    await crud.create_server_state(test_db, "test-server", True)

    # Upsert (should update)
    state = await crud.upsert_server_state(test_db, "test-server", False)

    # Verify
    assert state.server_id == "test-server"
    assert state.enabled is False


@pytest.mark.asyncio
async def test_delete_server_state(test_db: AsyncSession):
    """Test deleting a server state"""
    # Create
    await crud.create_server_state(test_db, "test-server", True)

    # Delete
    deleted = await crud.delete_server_state(test_db, "test-server")
    assert deleted is True

    # Verify deleted
    state = await crud.get_server_state(test_db, "test-server")
    assert state is None


@pytest.mark.asyncio
async def test_delete_server_state_not_found(test_db: AsyncSession):
    """Test deleting a non-existent server state"""
    result = await crud.delete_server_state(test_db, "non-existent")
    assert result is False


@pytest.mark.asyncio
async def test_get_all_server_states(test_db: AsyncSession):
    """Test retrieving all server states"""
    # Create multiple states
    await crud.create_server_state(test_db, "server1", True)
    await crud.create_server_state(test_db, "server2", False)
    await crud.create_server_state(test_db, "server3", True)

    # Retrieve all
    states = await crud.get_all_server_states(test_db)

    # Verify
    assert len(states) == 3
    server_ids = [s.server_id for s in states]
    assert "server1" in server_ids
    assert "server2" in server_ids
    assert "server3" in server_ids


@pytest.mark.asyncio
async def test_persistence_after_toggle(test_db: AsyncSession):
    """Test that state persists after multiple toggles"""
    # Create
    await crud.create_server_state(test_db, "test-server", True)

    # Toggle OFF
    await crud.upsert_server_state(test_db, "test-server", False)
    state = await crud.get_server_state(test_db, "test-server")
    assert state.enabled is False

    # Toggle ON
    await crud.upsert_server_state(test_db, "test-server", True)
    state = await crud.get_server_state(test_db, "test-server")
    assert state.enabled is True

    # Toggle OFF again
    await crud.upsert_server_state(test_db, "test-server", False)
    state = await crud.get_server_state(test_db, "test-server")
    assert state.enabled is False


@pytest.mark.asyncio
async def test_set_server_enabled_by_name_syncs_registry(test_db: AsyncSession):
    """Ensure server registry toggles follow state updates"""
    server = MCPServerCreate(
        name="filesystem",
        enabled=True,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
        env={},
    )

    created = await server_crud.create_server(test_db, server)
    await test_db.commit()

    assert created.enabled is True

    synced = await server_crud.set_server_enabled_by_name(test_db, "filesystem", False)
    assert synced is not None
    assert synced.enabled is False

    # Subsequent call with same value should be no-op
    no_change = await server_crud.set_server_enabled_by_name(
        test_db, "filesystem", False
    )
    assert no_change is not None
    assert no_change.enabled is False

    # Unknown servers are safely ignored
    missing = await server_crud.set_server_enabled_by_name(
        test_db, "unknown-server", True
    )
    assert missing is None
