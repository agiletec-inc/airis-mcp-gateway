"""CRUD operations for MCP server state"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.mcp_server_state import MCPServerState


async def get_server_state(db: AsyncSession, server_id: str) -> MCPServerState | None:
    """Get server state by server_id"""
    result = await db.execute(
        select(MCPServerState).where(MCPServerState.server_id == server_id)
    )
    return result.scalar_one_or_none()


async def get_all_server_states(db: AsyncSession) -> list[MCPServerState]:
    """Get all server states"""
    result = await db.execute(select(MCPServerState))
    return list(result.scalars().all())


async def create_server_state(
    db: AsyncSession, server_id: str, enabled: bool
) -> MCPServerState:
    """Create new server state"""
    server_state = MCPServerState(server_id=server_id, enabled=enabled)
    db.add(server_state)
    await db.commit()
    await db.refresh(server_state)
    return server_state


async def update_server_state(
    db: AsyncSession, server_id: str, enabled: bool
) -> MCPServerState | None:
    """Update server state"""
    server_state = await get_server_state(db, server_id)
    if not server_state:
        return None

    server_state.enabled = enabled
    await db.commit()
    await db.refresh(server_state)
    return server_state


async def upsert_server_state(
    db: AsyncSession, server_id: str, enabled: bool
) -> MCPServerState:
    """Create or update server state"""
    existing = await get_server_state(db, server_id)
    if existing:
        existing.enabled = enabled
        await db.commit()
        await db.refresh(existing)
        return existing
    else:
        return await create_server_state(db, server_id, enabled)


async def delete_server_state(db: AsyncSession, server_id: str) -> bool:
    """Delete server state"""
    server_state = await get_server_state(db, server_id)
    if not server_state:
        return False

    await db.delete(server_state)
    await db.commit()
    return True
