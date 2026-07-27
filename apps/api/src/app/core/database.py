"""
Database module - supports both lite mode (no DB) and full mode (with PostgreSQL).

Lite mode: Returns None for DB sessions, uses stub Base
Full mode: Returns async PostgreSQL sessions via SQLAlchemy
"""

import os
from typing import AsyncGenerator, Optional

# Check if we have SQLAlchemy available and DB configured
_GATEWAY_MODE = os.getenv("GATEWAY_MODE", "lite")
_DATABASE_URL = os.getenv("DATABASE_URL", "")

# Try to import SQLAlchemy
try:
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        create_async_engine,
        async_sessionmaker,
    )
    from sqlalchemy.orm import DeclarativeBase

    _HAS_SQLALCHEMY = True
except ImportError:
    _HAS_SQLALCHEMY = False

# Initialize based on mode
if _HAS_SQLALCHEMY and _DATABASE_URL and _GATEWAY_MODE == "full":
    # Full mode with actual DB
    engine = create_async_engine(_DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    class Base(DeclarativeBase):
        """SQLAlchemy declarative base for models"""

        pass

    def is_db_available() -> bool:
        return True

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSessionLocal() as session:  # pyright: ignore[reportOptionalCall,reportGeneralTypeIssues]
            yield session

elif _HAS_SQLALCHEMY:
    # SQLAlchemy available but lite mode or no DB URL - for testing
    from sqlalchemy.orm import DeclarativeBase

    class Base(DeclarativeBase):
        """SQLAlchemy declarative base for models (test/lite mode)"""

        pass

    engine = None
    AsyncSessionLocal = None

    def is_db_available() -> bool:
        return False

    async def get_db() -> AsyncGenerator[Optional[object], None]:
        yield None

else:
    # No SQLAlchemy - pure lite mode
    class Base:
        """Stub base class when SQLAlchemy not available"""

        pass

    engine = None
    AsyncSessionLocal = None

    def is_db_available() -> bool:
        return False

    async def get_db() -> AsyncGenerator[Optional[object], None]:
        yield None
