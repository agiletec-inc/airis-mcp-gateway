"""API endpoints for MCP server state management"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from ...core.database import get_db
from ...schemas import mcp_server_state as schemas
from ...crud import mcp_server_state as crud
from ...crud import mcp_server as server_crud

router = APIRouter(tags=["mcp-server-states"])


@router.get("/", response_model=schemas.MCPServerStateListResponse)
async def list_server_states(db: AsyncSession = Depends(get_db)):
    """List all server states"""
    states = await crud.get_all_server_states(db)
    return {"server_states": states, "total": len(states)}


@router.get("/{server_id}", response_model=schemas.MCPServerStateResponse)
async def get_server_state(server_id: str, db: AsyncSession = Depends(get_db)):
    """Get server state by server_id"""
    state = await crud.get_server_state(db, server_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server state for '{server_id}' not found",
        )
    return state


@router.put("/{server_id}", response_model=schemas.MCPServerStateResponse)
async def upsert_server_state(
    server_id: str,
    state_data: schemas.MCPServerStateUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Create or update server state"""
    state = await crud.upsert_server_state(db, server_id, state_data.enabled)
    # Keep core MCP server registry in sync when present
    await server_crud.set_server_enabled_by_name(db, server_id, state_data.enabled)
    return state


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server_state(server_id: str, db: AsyncSession = Depends(get_db)):
    """Delete server state"""
    deleted = await crud.delete_server_state(db, server_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server state for '{server_id}' not found",
        )
