"""Unit tests for secrets CRUD operations"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.crud import secret as crud
from app.core.database import Base


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
async def test_create_secret(test_db: AsyncSession):
    """Test creating a new secret"""
    # Create
    secret = await crud.create_secret(
        test_db, "test-server", "API_KEY", "test-secret-value"
    )

    # Verify
    assert secret.server_name == "test-server"
    assert secret.key_name == "API_KEY"
    assert secret.encrypted_value is not None
    assert isinstance(secret.encrypted_value, bytes)


@pytest.mark.asyncio
async def test_get_secret(test_db: AsyncSession):
    """Test retrieving a secret"""
    # Create
    await crud.create_secret(test_db, "test-server", "API_KEY", "test-value")

    # Retrieve
    secret = await crud.get_secret(test_db, "test-server", "API_KEY")

    # Verify
    assert secret is not None
    assert secret.server_name == "test-server"
    assert secret.key_name == "API_KEY"


@pytest.mark.asyncio
async def test_get_secret_value_decryption(test_db: AsyncSession):
    """Test decrypting secret value"""
    original_value = "my-secret-api-key"

    # Create
    await crud.create_secret(test_db, "test-server", "API_KEY", original_value)

    # Retrieve and decrypt
    decrypted = await crud.get_secret_value(test_db, "test-server", "API_KEY")

    # Verify
    assert decrypted == original_value


@pytest.mark.asyncio
async def test_get_secret_not_found(test_db: AsyncSession):
    """Test retrieving a non-existent secret"""
    secret = await crud.get_secret(test_db, "non-existent", "API_KEY")
    assert secret is None


@pytest.mark.asyncio
async def test_update_secret(test_db: AsyncSession):
    """Test updating a secret value"""
    # Create
    await crud.create_secret(test_db, "test-server", "API_KEY", "old-value")

    # Update
    new_value = "new-value"
    updated = await crud.update_secret(test_db, "test-server", "API_KEY", new_value)

    # Verify
    assert updated is not None
    decrypted = await crud.get_secret_value(test_db, "test-server", "API_KEY")
    assert decrypted == new_value


@pytest.mark.asyncio
async def test_delete_secret(test_db: AsyncSession):
    """Test deleting a secret"""
    # Create
    await crud.create_secret(test_db, "test-server", "API_KEY", "test-value")

    # Delete
    deleted = await crud.delete_secret(test_db, "test-server", "API_KEY")
    assert deleted is True

    # Verify deleted
    secret = await crud.get_secret(test_db, "test-server", "API_KEY")
    assert secret is None


@pytest.mark.asyncio
async def test_get_secrets_by_server(test_db: AsyncSession):
    """Test retrieving all secrets for a server"""
    # Create multiple secrets
    await crud.create_secret(test_db, "server1", "API_KEY", "value1")
    await crud.create_secret(test_db, "server1", "SECRET_KEY", "value2")
    await crud.create_secret(test_db, "server2", "API_KEY", "value3")

    # Retrieve server1 secrets
    secrets = await crud.get_secrets_by_server(test_db, "server1")

    # Verify
    assert len(secrets) == 2
    key_names = [s.key_name for s in secrets]
    assert "API_KEY" in key_names
    assert "SECRET_KEY" in key_names


@pytest.mark.asyncio
async def test_get_all_secrets(test_db: AsyncSession):
    """Test retrieving all secrets"""
    # Create multiple secrets
    await crud.create_secret(test_db, "server1", "API_KEY", "value1")
    await crud.create_secret(test_db, "server2", "SECRET_KEY", "value2")
    await crud.create_secret(test_db, "server3", "TOKEN", "value3")

    # Retrieve all
    secrets = await crud.get_all_secrets(test_db)

    # Verify
    assert len(secrets) == 3


@pytest.mark.asyncio
async def test_delete_secrets_by_server(test_db: AsyncSession):
    """Test deleting all secrets for a server"""
    # Create multiple secrets
    await crud.create_secret(test_db, "server1", "API_KEY", "value1")
    await crud.create_secret(test_db, "server1", "SECRET_KEY", "value2")
    await crud.create_secret(test_db, "server2", "API_KEY", "value3")

    # Delete server1 secrets
    count = await crud.delete_secrets_by_server(test_db, "server1")

    # Verify
    assert count == 2

    # Verify server1 secrets deleted
    secrets = await crud.get_secrets_by_server(test_db, "server1")
    assert len(secrets) == 0

    # Verify server2 secrets still exist
    secrets = await crud.get_secrets_by_server(test_db, "server2")
    assert len(secrets) == 1
