from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from ...core.database import get_db
from ...schemas.mcp_server import (
    MCPServerCreate,
    MCPServerUpdate,
    MCPServerResponse,
    MCPServerToggle,
)
from ...crud import mcp_server as crud

router = APIRouter()


@router.get("/", response_model=list[MCPServerResponse])
async def list_servers(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """List all MCP servers"""
    servers = await crud.get_servers(db, skip=skip, limit=limit)
    return servers


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_server(
    server_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get specific MCP server"""
    server = await crud.get_server_by_id(db, server_id)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with id {server_id} not found",
        )
    return server


@router.post("/", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    server: MCPServerCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create new MCP server"""
    try:
        return await crud.create_server(db, server)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_server(
    server_id: int,
    server_update: MCPServerUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update MCP server"""
    server = await crud.update_server(db, server_id, server_update)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with id {server_id} not found",
        )
    return server


@router.post("/{server_id}/toggle", response_model=MCPServerResponse)
async def toggle_server(
    server_id: int,
    toggle: MCPServerToggle,
    db: AsyncSession = Depends(get_db),
):
    """Toggle MCP server enabled status"""
    server = await crud.toggle_server(db, server_id, toggle.enabled)
    if not server:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with id {server_id} not found",
        )
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete MCP server"""
    success = await crud.delete_server(db, server_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server with id {server_id} not found",
        )
