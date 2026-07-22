"""
Pytest configuration and fixtures for API tests
"""

import pytest
import sys
import os
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

# Add src to Python path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Test database URL (uses same PostgreSQL as main app)
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/mcp_gateway"
)


@pytest.fixture
async def db_session():
    """Create test database session"""
    # Use NullPool for tests to avoid connection issues
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

    # Create session
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        # Start a transaction
        async with session.begin():
            yield session
            # Rollback after test (don't commit)
            await session.rollback()

    await engine.dispose()
