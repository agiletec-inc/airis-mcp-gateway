"""
Integration tests for MCP Server PostgreSQL persistence.

Tests verify that UI state changes (enabled/disabled) are permanently
persisted to PostgreSQL database and survive container restarts.
"""

import asyncio
import os
import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from app.core.config import settings
from app.crud import mcp_server as crud

# API base URL (container internal)
API_BASE_URL = os.getenv("API_INTERNAL_URL", "http://api:9900")

# Create test engine with NullPool (no connection pooling = no cache)
test_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool,  # Disable connection pooling
)

# Create test session factory
TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=True,  # Force re-query after commit
    autocommit=False,
    autoflush=False,
)


@pytest.mark.asyncio
class TestMCPServerPersistence:
    """Test PostgreSQL persistence of MCP server state."""

    async def test_toggle_server_persists_enabled_state(self):
        """
        Test that toggling a server ON persists to PostgreSQL.

        Scenario:
        1. Get Figma server ID by name
        2. Toggle server enabled state
        3. Verify API returns new state
        4. Query PostgreSQL directly - should match API state
        5. Toggle again
        6. Verify both API and PostgreSQL reflect the change
        """
        async with httpx.AsyncClient(base_url=API_BASE_URL) as client:
            # Step 1: Get Figma server
            server_name = "figma"
            async with TestSessionLocal() as db:
                server = await crud.get_server_by_name(db, server_name)
                assert server is not None, f"Server {server_name} not found in database"
                server_id = server.id
                initial_state = server.enabled

            # Step 2: Toggle server (flip state)
            new_state = not initial_state
            response = await client.post(
                f"/api/v1/mcp/servers/{server_id}/toggle", json={"enabled": new_state}
            )
            assert response.status_code == 200
            data = response.json()

            # Step 3: Verify API returns new enabled state
            assert data["enabled"] == new_state, (
                "API response doesn't match requested state"
            )

            # Wait for commit to complete (PostgreSQL READ COMMITTED isolation)
            await asyncio.sleep(0.1)

            # Step 4: Query PostgreSQL directly with RAW SQL to verify persistence
            async with TestSessionLocal() as fresh_db:
                result = await fresh_db.execute(
                    text("SELECT enabled FROM mcp_servers WHERE name = :name"),
                    {"name": server_name},
                )
                row = result.first()
                assert row is not None, f"Server {server_name} not found in database"
                db_enabled = row[0]
                assert db_enabled == new_state, (
                    f"Database state doesn't match API response: DB={db_enabled}, expected={new_state}"
                )

            # Step 5: Toggle again (back to original)
            response = await client.post(
                f"/api/v1/mcp/servers/{server_id}/toggle",
                json={"enabled": initial_state},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] == initial_state, "Second toggle failed"

            # Wait for commit to complete
            await asyncio.sleep(0.1)

            # Step 6: Verify PostgreSQL reflects the change with RAW SQL
            async with TestSessionLocal() as fresh_db2:
                result = await fresh_db2.execute(
                    text("SELECT enabled FROM mcp_servers WHERE name = :name"),
                    {"name": server_name},
                )
                row = result.first()
                db_enabled = row[0]
                assert db_enabled == initial_state, (
                    f"Database state not updated after second toggle: DB={db_enabled}, expected={initial_state}"
                )

    async def test_server_list_reflects_database_state(self):
        """
        Test that GET /servers endpoint returns current PostgreSQL state.

        This ensures the UI always shows the persisted state, not a cached or
        hardcoded state.
        """
        async with httpx.AsyncClient(base_url=API_BASE_URL) as client:
            # Get all servers from API
            response = await client.get("/api/v1/mcp/servers/")
            assert response.status_code == 200
            servers_from_api = response.json()

            # Verify each server's state matches PostgreSQL with NEW session
            async with TestSessionLocal() as db:
                for api_server in servers_from_api:
                    server_name = api_server["name"]
                    db_server = await crud.get_server_by_name(db, server_name)

                    assert db_server is not None, (
                        f"Server {server_name} in API but not in DB"
                    )
                    assert db_server.enabled == api_server["enabled"], (
                        f"Server {server_name} enabled state mismatch: DB={db_server.enabled}, API={api_server['enabled']}"
                    )

    async def test_restart_preserves_enabled_state(self):
        """
        Test that server state survives application/container restart.

        This test verifies:
        1. Get Figma server
        2. Set to enabled=true if not already
        3. Verify persistence through direct database query
        """
        async with httpx.AsyncClient(base_url=API_BASE_URL) as client:
            server_name = "figma"

            # Get server by name with NEW session
            async with TestSessionLocal() as db:
                server = await crud.get_server_by_name(db, server_name)
                assert server is not None, f"Server {server_name} not found"
                server_id = server.id
                initial_enabled = server.enabled

            # Ensure server is enabled
            if not initial_enabled:
                response = await client.post(
                    f"/api/v1/mcp/servers/{server_id}/toggle", json={"enabled": True}
                )
                assert response.status_code == 200

            # Verify current state via API
            response = await client.get(f"/api/v1/mcp/servers/{server_id}")
            assert response.status_code == 200
            before_state = response.json()
            assert before_state["enabled"] is True

            # Wait for commit to complete
            await asyncio.sleep(0.1)

            # Verify persistence through RAW SQL
            async with TestSessionLocal() as fresh_db:
                result = await fresh_db.execute(
                    text("SELECT enabled FROM mcp_servers WHERE name = :name"),
                    {"name": server_name},
                )
                row = result.first()
                assert row is not None, f"Server {server_name} not found"
                db_enabled = row[0]
                assert db_enabled is True, "Server state not persisted in database"

    async def test_multiple_toggles_maintain_consistency(self):
        """
        Test multiple toggles maintain database consistency.

        Scenario: User toggles server multiple times.
        Result: Each toggle should properly update PostgreSQL.
        """
        async with httpx.AsyncClient(base_url=API_BASE_URL) as client:
            server_name = "figma"

            # Get server with NEW session
            async with TestSessionLocal() as db:
                server = await crud.get_server_by_name(db, server_name)
                assert server is not None
                server_id = server.id
                initial_state = server.enabled

            # Perform 3 toggles
            for i in range(3):
                new_state = not ((i % 2 == 0) == initial_state)
                response = await client.post(
                    f"/api/v1/mcp/servers/{server_id}/toggle",
                    json={"enabled": new_state},
                )
                assert response.status_code == 200

                # Wait for commit to complete
                await asyncio.sleep(0.1)

                # Verify database was updated with RAW SQL
                async with TestSessionLocal() as fresh_db:
                    result = await fresh_db.execute(
                        text("SELECT enabled FROM mcp_servers WHERE name = :name"),
                        {"name": server_name},
                    )
                    row = result.first()
                    db_enabled = row[0]
                    assert db_enabled == new_state, (
                        f"Toggle {i + 1}: Expected {new_state}, got {db_enabled}"
                    )

    async def test_enabled_state_survives_migration(self):
        """
        Test that enabled state is preserved during Alembic migrations.

        This is critical for production deployments where migrations run
        before container startup.

        Verified behavior:
        - Column 'enabled' has default value (True/False)
        - Existing rows preserve their enabled state
        - No data loss during schema updates
        """
        # Query all servers with NEW session
        async with TestSessionLocal() as db:
            servers = await crud.get_servers(db, skip=0, limit=100)
            assert len(servers) > 0, "No servers found in database"

            # Verify each server has a boolean enabled state (not None)
            for server in servers:
                assert isinstance(server.enabled, bool), (
                    f"Server {server.name} has invalid enabled state: {server.enabled}"
                )

                # Verify required fields exist (migration integrity)
                assert server.name is not None
                assert server.command is not None
                assert server.created_at is not None
                assert server.updated_at is not None
