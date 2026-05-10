"""
Process MCP API Endpoints

Routes for process-based MCP servers (uvx/npx).
These endpoints handle direct process communication without Docker Gateway.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Optional

from ...core.process_manager import get_process_manager

router = APIRouter()


class ToolCallRequest(BaseModel):
    """Request body for tools/call."""
    name: str = Field(..., description="Tool name to call")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class ToolCallResponse(BaseModel):
    """Response from tools/call."""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None


class ServerStatusResponse(BaseModel):
    """Server status information."""
    name: str
    type: str
    command: Optional[str] = None
    enabled: bool
    state: str
    tools_count: int


@router.get("/servers")
async def list_process_servers():
    """
    List all registered process MCP servers.

    Returns:
        List of server status objects
    """
    manager = get_process_manager()
    return {
        "servers": manager.get_all_status()
    }


@router.get("/servers/{server_name}")
async def get_server_status(server_name: str):
    """
    Get status of a specific process MCP server.

    Args:
        server_name: Server name to query

    Returns:
        Server status object
    """
    manager = get_process_manager()

    if not manager.is_process_server(server_name):
        raise HTTPException(404, f"Server not found: {server_name}")

    return manager.get_server_status(server_name)


@router.post("/servers/{server_name}/enable")
async def enable_server(server_name: str):
    """
    Enable a process MCP server.

    Args:
        server_name: Server name to enable

    Returns:
        Updated server status
    """
    manager = get_process_manager()

    if not manager.is_process_server(server_name):
        raise HTTPException(404, f"Server not found: {server_name}")

    await manager.enable_server(server_name)
    return manager.get_server_status(server_name)


@router.post("/servers/{server_name}/disable")
async def disable_server(server_name: str):
    """
    Disable a process MCP server (stops process if running).

    Args:
        server_name: Server name to disable

    Returns:
        Updated server status
    """
    manager = get_process_manager()

    if not manager.is_process_server(server_name):
        raise HTTPException(404, f"Server not found: {server_name}")

    await manager.disable_server(server_name)
    return manager.get_server_status(server_name)


@router.get("/tools")
async def list_tools(
    server: Optional[str] = Query(None, description="Filter by server name"),
    mode: Optional[str] = Query("all", description="Filter by mode: hot, cold, all (default: all)")
):
    """
    List available tools from process MCP servers.

    Args:
        server: Optional server name filter
        mode: Filter by server mode (hot, cold, all). Default: all

    Returns:
        List of tool definitions
    """
    manager = get_process_manager()
    tools = await manager.list_tools(server_name=server, mode=mode)
    return {"tools": tools}


@router.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """
    Call a tool on a process MCP server (auto-routes to correct server).

    Args:
        request: Tool call request

    Returns:
        Tool call result
    """
    manager = get_process_manager()
    response = await manager.call_tool(request.name, request.arguments)

    # `"error": null` is "no error" — some servers (e.g. airis-workspace) emit
    # it alongside a successful result.
    error = response.get("error")
    if error is not None and error.get("code") in (-32602, -32000):
        # Validation error: inject full schema so the caller can self-heal on retry.
        from ...core.dynamic_mcp import get_dynamic_mcp
        schema_info = get_dynamic_mcp().get_tool_schema(request.name)
        input_schema = schema_info.get("inputSchema") if schema_info else None
        if input_schema:
            error["message"] += f"\n\nFull Schema: {input_schema}"
            error["hint"] = "Retry with the full schema provided above."

    return response


@router.post("/tools/call/{server_name}")
async def call_tool_on_server(
    server_name: str,
    request: ToolCallRequest
):
    """
    Call a tool on a specific process MCP server.

    Args:
        server_name: Target server name
        request: Tool call request

    Returns:
        Tool call result
    """
    manager = get_process_manager()

    if not manager.is_process_server(server_name):
        raise HTTPException(404, f"Server not found: {server_name}")

    response = await manager.call_tool_on_server(
        server_name,
        request.name,
        request.arguments
    )

    return response


@router.post("/rpc/{server_name}")
async def send_rpc_request(
    server_name: str,
    request: dict[str, Any]
):
    """
    Send a raw JSON-RPC request to a process MCP server.

    Args:
        server_name: Target server name
        request: JSON-RPC request body

    Returns:
        JSON-RPC response
    """
    manager = get_process_manager()

    if not manager.is_process_server(server_name):
        raise HTTPException(404, f"Server not found: {server_name}")

    response = await manager.send_request(server_name, request)
    return response
