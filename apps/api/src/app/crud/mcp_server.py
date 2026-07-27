from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models.mcp_server import MCPServer
from ..schemas.mcp_server import MCPServerCreate, MCPServerUpdate


async def get_servers(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> list[MCPServer]:
    """Get all MCP servers"""
    result = await db.execute(
        select(MCPServer).offset(skip).limit(limit).order_by(MCPServer.name)
    )
    return list(result.scalars().all())


async def get_server_by_id(db: AsyncSession, server_id: int) -> MCPServer | None:
    """Get MCP server by ID"""
    result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
    return result.scalar_one_or_none()


async def get_server_by_name(db: AsyncSession, name: str) -> MCPServer | None:
    """Get MCP server by name"""
    result = await db.execute(select(MCPServer).where(MCPServer.name == name))
    return result.scalar_one_or_none()


async def create_server(db: AsyncSession, server: MCPServerCreate) -> MCPServer:
    """Create new MCP server"""
    db_server = MCPServer(**server.model_dump())
    db.add(db_server)
    try:
        await db.flush()
        await db.refresh(db_server)
        return db_server
    except IntegrityError:
        await db.rollback()
        raise ValueError(f"Server with name '{server.name}' already exists")


async def update_server(
    db: AsyncSession, server_id: int, server_update: MCPServerUpdate
) -> MCPServer | None:
    """Update MCP server"""
    db_server = await get_server_by_id(db, server_id)
    if not db_server:
        return None

    update_data = server_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_server, field, value)

    await db.flush()
    await db.refresh(db_server)
    return db_server


async def toggle_server(
    db: AsyncSession, server_id: int, enabled: bool
) -> MCPServer | None:
    """Toggle MCP server enabled status"""
    db_server = await get_server_by_id(db, server_id)
    if not db_server:
        return None

    db_server.enabled = enabled
    await db.flush()
    await db.refresh(db_server)
    return db_server


async def delete_server(db: AsyncSession, server_id: int) -> bool:
    """Delete MCP server"""
    db_server = await get_server_by_id(db, server_id)
    if not db_server:
        return False

    await db.delete(db_server)
    await db.flush()
    return True


async def set_server_enabled_by_name(
    db: AsyncSession, name: str, enabled: bool
) -> MCPServer | None:
    """Set server enabled flag by name (no-op if server not found)"""
    db_server = await get_server_by_name(db, name)
    if not db_server:
        return None

    if db_server.enabled == enabled:
        return db_server

    db_server.enabled = enabled
    await db.commit()
    await db.refresh(db_server)
    return db_server
