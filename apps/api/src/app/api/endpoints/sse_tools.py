"""
SSE Tools Endpoint - Real-time tool discovery across Docker + Process MCP servers.

Events:
- server_status: Server state changes (started, stopped, ready, error)
- tools_list: Full tools list from a server
- tool_added: New tool discovered
- tool_removed: Tool no longer available
- heartbeat: Keep-alive (every 30s)
"""

import asyncio
import json
import time
from typing import Any, AsyncIterator
from dataclasses import dataclass, field
from collections import deque
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

from ...core.config import settings
from ...core.process_manager import get_process_manager
from ...core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Ring buffer for event backpressure
MAX_EVENT_QUEUE = 100


@dataclass
class SSEClient:
    """Tracks an SSE client connection."""

    id: str
    connected_at: float = field(default_factory=time.time)
    last_event_at: float = field(default_factory=time.time)
    events_sent: int = 0


class SSEToolsPublisher:
    """
    Manages SSE subscriptions for tool discovery.

    Aggregates events from:
    - Docker MCP Gateway (port 9390)
    - Process MCP servers (uvx/npx)
    """

    def __init__(self):
        self._clients: dict[str, SSEClient] = {}
        self._event_queue: deque = deque(maxlen=MAX_EVENT_QUEUE)
        self._client_counter = 0
        self._lock = asyncio.Lock()

        # Metrics
        self.total_events_sent = 0
        self.overflow_events = 0

    def _next_client_id(self) -> str:
        self._client_counter += 1
        return f"sse-{self._client_counter}"

    async def add_client(self) -> str:
        """Register a new SSE client."""
        async with self._lock:
            client_id = self._next_client_id()
            self._clients[client_id] = SSEClient(id=client_id)
            logger.info(f"Client {client_id} connected (total: {len(self._clients)})")
            return client_id

    async def remove_client(self, client_id: str):
        """Unregister an SSE client."""
        async with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
                logger.info(
                    f"Client {client_id} disconnected (total: {len(self._clients)})"
                )

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def get_stats(self) -> dict[str, Any]:
        """Get publisher stats for /healthz."""
        return {
            "active_clients": len(self._clients),
            "total_events_sent": self.total_events_sent,
            "overflow_events": self.overflow_events,
            "queue_size": len(self._event_queue),
            "queue_max": MAX_EVENT_QUEUE,
        }


# Global publisher instance
_publisher = SSEToolsPublisher()


def format_sse_event(event_type: str, data: Any) -> str:
    """Format data as SSE event."""
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {json_data}\n\n"


async def get_docker_gateway_tools() -> list[dict[str, Any]]:
    """Fetch tools from Docker MCP Gateway."""
    try:
        async with httpx.AsyncClient(timeout=10.0):
            # Docker Gateway doesn't have a direct tools endpoint
            # We get tools via the SSE stream, so return empty here
            # The actual tools come through the MCP protocol
            return []
    except Exception as e:
        logger.error(f"Failed to fetch Docker Gateway tools: {e}")
        return []


async def get_all_server_status() -> list[dict[str, Any]]:
    """Get status of all servers (Docker + Process)."""
    servers = []

    # Docker Gateway status
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.MCP_GATEWAY_URL}/health")
            docker_status = "ready" if resp.status_code == 200 else "error"
    except (httpx.RequestError, httpx.HTTPStatusError):
        # Catch all network errors for health check
        docker_status = "unreachable"

    servers.append(
        {
            "name": "docker-gateway",
            "type": "docker",
            "status": docker_status,
            "url": settings.MCP_GATEWAY_URL,
        }
    )

    # Process servers status
    try:
        manager = get_process_manager()
        for status in manager.get_all_status():
            servers.append(
                {
                    "name": status["name"],
                    "type": "process",
                    "status": status["state"],
                    "command": status.get("command", ""),
                    "enabled": status.get("enabled", False),
                    "tools_count": status.get("tools_count", 0),
                }
            )
    except Exception as e:
        logger.error(f"Failed to get process status: {e}")

    return servers


def _apply_brief_description(description: str, mode: str = "brief") -> str:
    """Apply brief description mode (similar to mcp_proxy logic)."""
    if not description or mode == "none":
        return ""
    if mode == "full":
        return description

    max_length = 160 if mode == "summary" else 60
    text = description.strip()

    for delimiter in [". ", "。", "！", "?", "？", "\n"]:
        idx = text.find(delimiter)
        if 0 < idx:
            if delimiter == "\n":
                text = text[:idx]
            else:
                text = text[: idx + len(delimiter.strip())]
            break

    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


async def get_combined_tools(
    mode: str = "hot", description_mode: str = "brief"
) -> dict[str, Any]:
    """
    Get all tools from all sources with brief descriptions.

    Args:
        mode: Tool listing mode ("hot", "cold", "all")
        description_mode: Description verbosity ("full", "summary", "brief", "none")

    Returns:
        {
            "servers": [...],
            "tools": [...],
            "generatedAt": timestamp
        }
    """
    servers = await get_all_server_status()
    all_tools = []

    # Get tools from Process servers (HOT by default)
    try:
        manager = get_process_manager()
        process_tools = await manager.list_tools(mode=mode)
        for tool in process_tools:
            tool["_source"] = "process"
            # Apply brief description mode
            if "description" in tool:
                if description_mode == "none":
                    del tool["description"]
                else:
                    tool["description"] = _apply_brief_description(
                        tool["description"], description_mode
                    )
        all_tools.extend(process_tools)
    except Exception as e:
        logger.error(f"Failed to get process tools: {e}")

    return {
        "servers": servers,
        "tools": all_tools,
        "tools_count": len(all_tools),
        "description_mode": description_mode,
        "generatedAt": int(time.time()),
    }


async def sse_event_generator(client_id: str) -> AsyncIterator[str]:
    """
    Generate SSE events for a client.

    Flow:
    1. Send initial server_status for all servers
    2. Send initial tools_list
    3. Send heartbeat every 30s
    4. Send updates when state changes
    """
    try:
        # Initial burst: server status
        servers = await get_all_server_status()
        yield format_sse_event(
            "server_status",
            {
                "servers": servers,
                "timestamp": int(time.time()),
            },
        )

        # Initial burst: tools list
        combined = await get_combined_tools()
        yield format_sse_event(
            "tools_list",
            {
                "tools": combined["tools"],
                "tools_count": combined["tools_count"],
                "timestamp": int(time.time()),
            },
        )

        # Heartbeat loop with periodic status updates
        last_status_check = time.time()
        heartbeat_interval = 30
        status_check_interval = 10

        while True:
            await asyncio.sleep(1)

            now = time.time()

            # Periodic status check
            if now - last_status_check >= status_check_interval:
                last_status_check = now
                new_servers = await get_all_server_status()

                # Check for state changes
                if new_servers != servers:
                    servers = new_servers
                    yield format_sse_event(
                        "server_status",
                        {
                            "servers": servers,
                            "timestamp": int(now),
                        },
                    )

            # Heartbeat
            if int(now) % heartbeat_interval == 0:
                yield format_sse_event(
                    "heartbeat",
                    {
                        "timestamp": int(now),
                        "client_id": client_id,
                    },
                )

    except asyncio.CancelledError:
        logger.info(f"Client {client_id} stream cancelled")
        raise
    except Exception as e:
        logger.error(f"Client {client_id} stream error: {e}")
        yield format_sse_event(
            "error",
            {
                "message": str(e),
                "timestamp": int(time.time()),
            },
        )


@router.get("/sse/tools")
async def sse_tools_stream(request: Request):
    """
    SSE endpoint for real-time tool discovery.

    Events:
    - server_status: {servers: [...], timestamp: int}
    - tools_list: {tools: [...], tools_count: int, timestamp: int}
    - heartbeat: {timestamp: int, client_id: str}
    - error: {message: str, timestamp: int}
    """
    client_id = await _publisher.add_client()

    async def event_stream():
        try:
            async for event in sse_event_generator(client_id):
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                yield event
        finally:
            await _publisher.remove_client(client_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tools/combined")
async def get_tools_combined(mode: str = "hot", desc: str = "brief"):
    """
    Get combined tools list (SSE fallback for non-streaming clients).

    Query params:
        mode: Tool listing mode ("hot", "cold", "all"). Default: hot
        desc: Description verbosity ("full", "summary", "brief", "none"). Default: brief

    Returns:
        {
            "servers": [...],
            "tools": [...],
            "tools_count": int,
            "description_mode": str,
            "generatedAt": int
        }
    """
    return JSONResponse(await get_combined_tools(mode=mode, description_mode=desc))


@router.get("/tools/status")
async def get_tools_status(metrics: bool = False):
    """
    Get server status overview with optional SRE metrics.

    Query params:
        metrics: If true, include detailed metrics (uptime, latency, memory, etc.)

    Returns:
        {
            "roster": {hot: [...], cold: [...], summary: {...}},
            "servers": [...],
            "processes": [...],  # With metrics if requested
            "sse": {active_clients: int, ...}
        }
    """
    servers = await get_all_server_status()

    # Get process server status with optional metrics
    try:
        manager = get_process_manager()
        processes = manager.get_all_status(include_metrics=metrics)

        # Build roster summary
        hot_servers = manager.get_hot_servers()
        cold_servers = manager.get_cold_servers()
        roster = {
            "hot": hot_servers,
            "cold": cold_servers,
            "summary": {
                "hot_count": len(hot_servers),
                "cold_count": len(cold_servers),
                "total_enabled": len(hot_servers) + len(cold_servers),
            },
        }
    except Exception as e:
        logger.error(f"Failed to get process status with metrics: {e}")
        processes = []
        roster = {"hot": [], "cold": [], "summary": {}}

    return JSONResponse(
        {
            "roster": roster,
            "servers": servers,
            "processes": processes,
            "sse": _publisher.get_stats(),
        }
    )
