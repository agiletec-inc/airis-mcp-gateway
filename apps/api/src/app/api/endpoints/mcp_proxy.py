"""
MCP Proxy Endpoint with OpenMCP Lazy Loading Pattern

Claude Code → FastAPI (/mcp/sse) → Docker MCP Gateway (http://mcp-gateway:9390/sse)

This module is being split by responsibility as part of issue #86. The bits
that still live here are the SSE proxy streaming loop, the JSON-RPC proxy
routing, the Dynamic MCP handlers, and the FastAPI routes. Everything else
has moved to sibling modules:

* :mod:`session_queue` — per-session response queue lifecycle
* :mod:`sse_protocol` — SSE wire-format helpers (buffer, encode, decode)
* :mod:`tool_shaping` — tools/list / prompts/list response rewriting
* :mod:`gateway_stream_bridge` — Streamable HTTP ↔ Gateway SSE bridge

The symbols that other modules and tests import from ``mcp_proxy`` (such as
``cleanup_stale_queues``, ``_stream_bridge_sessions``, ``apply_schema_partitioning``)
are re-exported at the bottom of this file so those call sites keep working.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from typing import Any, AsyncGenerator, Dict, Optional
import httpx
import json
import asyncio
import time as _time_module
from ...core.schema_partitioning import schema_partitioner
from ...core.config import settings
from ...core.protocol_logger import protocol_logger
from ...core.process_manager import get_process_manager
from ...core.dynamic_mcp import get_dynamic_mcp
from ...core.behavior_compiler import compile_instructions
from ...core.logging import get_logger
from ...core.mcp_config_loader import ServerMode

# Responsibility-split modules. Imported with their public names so the rest
# of this file reads as if the helpers were still local.
from .session_queue import (
    _SESSION_QUEUE_TTL_SECONDS,
    _session_queues_lock,
    _session_response_queues,
    cleanup_stale_queues,
    get_response_queue,
    get_session_queue_count,
    remove_response_queue,
)
from .sse_protocol import (
    SSEEventBuffer,
    format_sse_event as _format_sse_event,
    parse_sse_json as _parse_sse_json,
)
from .tool_shaping import (
    DescriptionMode,
    apply_prompts_merging,
    apply_schema_partitioning,
    extract_server_name_from_tool as _extract_server_name_from_tool,
    summarize_description as _summarize_description,
)
from .gateway_stream_bridge import (
    STREAM_BRIDGE_READY_DELAY,
    STREAM_TIMEOUT,
    StreamBridgeSession,
    _stream_bridge_lock,
    _stream_bridge_sessions,
    cleanup_stale_stream_bridges,
    close_stream_bridge_session as _close_stream_bridge_session,
    delete_stream_bridge_session as _delete_stream_bridge_session,
    extract_gateway_session_id as _extract_gateway_session_id,
    get_or_create_stream_bridge_session as _get_or_create_stream_bridge_session,
    get_response_message_id as _get_response_message_id,
    get_stream_bridge_count,
    get_stream_session_id as _get_stream_session_id,
    send_via_stream_bridge as _send_via_stream_bridge,
    stream_session_header_name as _stream_session_header_name,
)

logger = get_logger(__name__)

router = APIRouter()

# =============================================================================
# HTTP Client Timeout Configuration
# =============================================================================
# SSE streams are long-lived, but we need timeouts to prevent indefinite hangs:
# - connect: Time to establish TCP connection (catches network issues)
# - read: Time to wait for next chunk (catches stale connections)
# - write: Time to send data (catches slow upstream)
# - pool: Time to acquire connection from pool
# =============================================================================

# Connection timeout constants (seconds)
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 120.0
WRITE_TIMEOUT = 10.0
POOL_TIMEOUT = 10.0
SSE_KEEPALIVE_INTERVAL = 30.0
INIT_CLIENT_TIMEOUT = 30.0
STREAM_BRIDGE_READY_DELAY = 0.3

# Track initialized sessions for auto-init fallback
_initialized_sessions: set[str] = set()

# SSE stream timeout - long read timeout for long-lived connections
SSE_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT,
    read=READ_TIMEOUT,
    write=WRITE_TIMEOUT,
    pool=POOL_TIMEOUT
)

# Streaming gateway timeout - similar to SSE
STREAM_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT,
    read=READ_TIMEOUT,
    write=WRITE_TIMEOUT,
    pool=POOL_TIMEOUT
)

# Standard JSON-RPC timeout - uses configurable TOOL_CALL_TIMEOUT
def get_jsonrpc_timeout() -> httpx.Timeout:
    """Get JSON-RPC timeout using configurable TOOL_CALL_TIMEOUT."""
    return httpx.Timeout(
        connect=10.0,
        read=settings.TOOL_CALL_TIMEOUT,
        write=10.0,
        pool=10.0
    )

async def proxy_sse_stream(request: Request):
    """
    SSEストリームをDocker MCP GatewayからProxyしてschema partitioning適用

    MCP SSE Transport では、サーバーのレスポンスは SSE ストリーム経由で送信される。
    ProcessManager のレスポンスもここで注入する。

    Args:
        request: FastAPI Request

    Yields:
        Server-Sent Events
    """
    initialize_request_id = None  # Track initialize request ID
    session_id = request.query_params.get("sessionid")  # Track session ID
    endpoint_url = None  # Track endpoint URL
    captured_session_id = None  # Session ID captured from Gateway

    # Codex streamable_http sometimes POSTs to /sse with Content-Length headers.
    # Strip entity headers so the proxied GET doesn't advertise a body it never sends.
    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"content-length", "content-type", "host"}
    }

    if not session_id:
        logger.info("SSE request missing sessionid", dict(request.headers))

    gateway_sse_url = _build_gateway_sse_url(request)

    async with httpx.AsyncClient(timeout=SSE_TIMEOUT) as client:
        async with client.stream(
            "GET",
            gateway_sse_url,
            headers=forward_headers,
        ) as response:

            async def read_gateway_stream():
                """Docker Gateway からの SSE メッセージを読み取る"""
                async for line in response.aiter_lines():
                    yield ("gateway", line)

            async def read_response_queue() -> AsyncGenerator[tuple[str, Any], None]:
                """ProcessManager のレスポンスキューから読み取る"""
                nonlocal captured_session_id
                while True:
                    if captured_session_id:
                        queue = await get_response_queue(captured_session_id)
                        try:
                            # Non-blocking check with timeout
                            response_data = await asyncio.wait_for(queue.get(), timeout=0.1)
                            yield ("process_manager", response_data)
                        except asyncio.TimeoutError:
                            yield ("tick", None)  # Keep the generator alive
                    else:
                        await asyncio.sleep(0.1)
                        yield ("tick", None)

            async def keepalive_sender():
                """Send periodic keepalive comments to prevent connection timeouts"""
                # SSE comment lines (: comment) are ignored by clients but keep connection alive
                while True:
                    await asyncio.sleep(SSE_KEEPALIVE_INTERVAL)
                    yield ("keepalive", None)

            # Merge all streams: gateway, response queue, and keepalive
            gateway_gen = read_gateway_stream()
            queue_gen = read_response_queue()
            keepalive_gen = keepalive_sender()

            gateway_task = None
            queue_task = None
            keepalive_task = None
            gateway_stream_alive = True
            sse_buffer = SSEEventBuffer()

            try:
                while True:
                    # Start tasks if needed
                    if gateway_task is None and gateway_stream_alive:
                        gateway_task = asyncio.create_task(gateway_gen.__anext__())
                    if queue_task is None:
                        queue_task = asyncio.create_task(queue_gen.__anext__())
                    if keepalive_task is None:
                        keepalive_task = asyncio.create_task(keepalive_gen.__anext__())

                    # Wait for any to complete (only include active tasks)
                    tasks_to_wait = [t for t in [gateway_task, queue_task, keepalive_task] if t is not None]
                    done, _ = await asyncio.wait(
                        tasks_to_wait,
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    for task in done:
                        try:
                            source, data = task.result()
                        except StopAsyncIteration:
                            if task is gateway_task:
                                # Gateway stream ended — continue serving process manager responses
                                logger.info(f"Gateway SSE stream ended, continuing with process manager (session={captured_session_id})")
                                gateway_task = None
                                gateway_stream_alive = False
                                continue
                            if captured_session_id:
                                await remove_response_queue(captured_session_id)
                            return
                        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError) as e:
                            if task is gateway_task:
                                logger.info(f"Gateway disconnected ({type(e).__name__}), continuing with process manager (session={captured_session_id})")
                                gateway_task = None
                                gateway_stream_alive = False
                                continue
                            # Client disconnected - this is normal, exit gracefully
                            logger.info(f"Client disconnected: {type(e).__name__}")
                            if captured_session_id:
                                await remove_response_queue(captured_session_id)
                            return
                        except httpx.ReadTimeout:
                            if task is gateway_task:
                                logger.info(f"Gateway SSE idle timeout, continuing with process manager (session={captured_session_id})")
                                gateway_task = None
                                gateway_stream_alive = False
                                continue
                            logger.info(f"SSE read timeout (session={captured_session_id})")
                            if captured_session_id:
                                await remove_response_queue(captured_session_id)
                            return
                        except httpx.TimeoutException as e:
                            if task is gateway_task:
                                logger.info(f"Gateway timeout ({type(e).__name__}), continuing with process manager (session={captured_session_id})")
                                gateway_task = None
                                gateway_stream_alive = False
                                continue
                            # Other timeout (connect, pool, etc.)
                            logger.info(f"Timeout exception: {type(e).__name__}")
                            if captured_session_id:
                                await remove_response_queue(captured_session_id)
                            return

                        if source == "tick":
                            queue_task = None
                            continue

                        if source == "keepalive":
                            # Send SSE comment as keepalive (ignored by clients)
                            keepalive_task = None
                            yield ": keepalive\n\n"
                            continue

                        if source == "process_manager":
                            # Send ProcessManager response via SSE
                            queue_task = None
                            logger.info(f"Sending ProcessManager response via SSE: id={data.get('id') if isinstance(data, dict) else None}")
                            yield f"event: message\ndata: {json.dumps(data)}\n\n"
                            continue

                        # Message from Gateway
                        gateway_task = None
                        line = data

                        if not line:
                            yield "\n"
                            continue

                        # SSE format: "event: xxx\n" or "data: {...}\n\n"
                        if line.startswith("event: endpoint"):
                            yield f"{line}\n"
                            continue

                        if line.startswith("data: "):
                            data_str = line[6:]  # Strip "data: " prefix

                            # Check if it's an endpoint URL (not JSON)
                            if not data_str.startswith("{") and not data_str.startswith("["):
                                # Extract sessionid from endpoint URL if present
                                if "sessionid=" in data_str:
                                    import re
                                    match = re.search(r'sessionid=([A-Z0-9]+)', data_str)
                                    if match:
                                        captured_session_id = match.group(1)
                                        endpoint_url = data_str.strip()
                                        logger.info(f"Captured endpoint URL with sessionid={captured_session_id}")
                                        # Create response queue for this session
                                        await get_response_queue(captured_session_id)
                                yield f"{line}\n"
                                continue

                            try:
                                json_data = json.loads(data_str)

                                # Detect initialize request (unlikely in SSE stream, but just in case)
                                if isinstance(json_data, dict) and json_data.get("method") == "initialize":
                                    initialize_request_id = json_data.get("id")
                                    logger.info(f"Detected initialize request (id={initialize_request_id})")
                                    await protocol_logger.log_message("client→server", json_data, {"phase": "initialize"})

                                # Intercept tools/list response
                                if isinstance(json_data, dict) and "result" in json_data and "tools" in json_data.get("result", {}):
                                    await protocol_logger.log_message("client→server", json_data, {"phase": "tools_list"})
                                    json_data = await apply_schema_partitioning(json_data)
                                    await protocol_logger.log_message("server→client", json_data, {"phase": "tools_list"})

                                # Intercept prompts/list response (merge Process MCP server prompts)
                                if isinstance(json_data, dict) and "result" in json_data and "prompts" in json_data.get("result", {}):
                                    json_data = await apply_prompts_merging(json_data)

                                # Inject instructions into initialize response
                                is_initialize_response = (
                                    isinstance(json_data, dict) and
                                    "result" in json_data and
                                    isinstance(json_data.get("result"), dict) and
                                    "protocolVersion" in json_data.get("result", {})
                                )
                                if is_initialize_response:
                                    from ...core.mcp_config_loader import load_mcp_config
                                    server_configs = load_mcp_config()
                                    json_data["result"]["instructions"] = compile_instructions(server_configs)

                                # Yield transformed data
                                yield f"data: {json.dumps(json_data)}\n\n"

                                # On initialize response, POST notifications/initialized to Gateway
                                if is_initialize_response:

                                    logger.info(f"Detected initialize response, sending initialized notification to Gateway")
                                    await protocol_logger.log_message("server→client", json_data, {"phase": "initialize"})

                                    # POST notifications/initialized to Gateway
                                    initialized_notification = {
                                        "jsonrpc": "2.0",
                                        "method": "notifications/initialized"
                                    }

                                    # POST to Gateway using sessionid
                                    if captured_session_id:
                                        gateway_post_url = f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse?sessionid={captured_session_id}"
                                        try:
                                            post_response = await client.post(
                                                gateway_post_url,
                                                json=initialized_notification,
                                                headers={"Content-Type": "application/json"}
                                            )
                                            logger.info(f"Sent initialized notification to Gateway: {post_response.status_code}")
                                        except Exception as e:
                                            logger.error(f"Failed to send initialized notification: {e}")
                                    else:
                                        logger.info("No sessionid available, cannot send initialized notification")

                            except json.JSONDecodeError as e:
                                # Log malformed JSON for debugging (truncate to avoid log spam)
                                logger.info(f"Malformed JSON in SSE data: {str(e)[:100]}")
                                yield f"{line}\n"
                        else:
                            yield f"{line}\n"
            finally:
                # Cancel any pending tasks to prevent "Task exception was never retrieved"
                for task in [gateway_task, queue_task, keepalive_task]:
                    if task is not None and not task.done():
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, StopAsyncIteration):
                            pass
                # Cleanup session queue
                if captured_session_id:
                    await remove_response_queue(captured_session_id)
                logger.info(f"SSE stream cleanup complete (session={captured_session_id})")


async def apply_prompts_merging(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    prompts/list レスポンスに Process MCP サーバーのプロンプトを追加

    Args:
        data: prompts/list JSON-RPC 2.0 レスポンス

    Returns:
        プロンプトがマージされたレスポンス
    """
    if "result" not in data or "prompts" not in data["result"]:
        return data

    prompts = list(data["result"]["prompts"])

    # Fetch and merge prompts from Process MCP servers
    try:
        process_manager = get_process_manager()
        process_prompts = await process_manager.list_prompts(mode="hot")
        if process_prompts:
            logger.info(f"Merging {len(process_prompts)} HOT prompts with {len(prompts)} docker prompts")
            prompts.extend(process_prompts)
    except Exception as e:
        logger.error(f"Failed to get process prompts: {e}")

    data["result"]["prompts"] = prompts
    return data


async def _refresh_dynamic_mcp_cache(process_manager, docker_tools: list):
    """Background task to refresh Dynamic MCP cache without blocking response."""
    try:
        dynamic_mcp = get_dynamic_mcp()
        await dynamic_mcp.refresh_cache_hot_only(process_manager, docker_tools)

        # Store schemas for cached tools
        for tool_name, tool_info in dynamic_mcp._tools.items():
            schema_partitioner.store_full_schema(tool_name, tool_info.input_schema)
            schema_partitioner.store_tool_description(tool_name, tool_info.description)

        logger.info(f"Background cache refresh complete: {len(dynamic_mcp._tools)} tools")
    except Exception as e:
        logger.error(f"Background cache refresh failed: {e}")


async def apply_schema_partitioning(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    tools/list レスポンスにschema partitioning適用 + Process MCPツール統合

    Args:
        data: tools/list JSON-RPC 2.0 レスポンス

    Returns:
        Schema partitioningされたレスポンス（Docker + Process統合）
        DYNAMIC_MCP=true の場合はメタツールのみ返す
    """
    if "result" not in data or "tools" not in data["result"]:
        return data

    docker_tools = list(data["result"]["tools"])
    process_manager = get_process_manager()

    # Dynamic MCP mode: meta-tools + HOT server tools with full schema
    # COLD servers are accessed directly via airis-exec (tool names listed in description)
    if settings.DYNAMIC_MCP:
        dynamic_mcp = get_dynamic_mcp()
        dynamic_mcp.refresh_toolsets(process_manager)
        excluded_servers = {"airis-mcp-gateway-control", "airis-commands"}

        # HOT servers: expose full schema directly (skip internal management servers)
        # Uses asyncio.gather for parallel startup, with per-server timeout
        hot_tool_names: set[str] = set()
        hot_tools_list: list[dict] = []
        try:
            hot_servers = [
                s for s in process_manager.get_hot_servers()
                if s not in excluded_servers
            ]

            async def get_tools_for_server(name: str) -> list[dict]:
                try:
                    return await asyncio.wait_for(
                        process_manager.list_tools(server_name=name),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout listing tools for {name}, skipping")
                    return []
                except Exception as e:
                    logger.error(f"Error listing tools for {name}: {e}")
                    return []

            results = await asyncio.gather(
                *[get_tools_for_server(s) for s in hot_servers]
            )
            for server_tools in results:
                for t in server_tools:
                    hot_tool_names.add(t.get("name", ""))
                hot_tools_list.extend(server_tools)
        except Exception as e:
            logger.error(f"Failed to list HOT tools: {e}")

        tools = list(dynamic_mcp.get_meta_tools(mode=settings.META_TOOLS_MODE))
        meta_count = len(tools)
        tools.extend(hot_tools_list)
        active_tools_list = dynamic_mcp.get_active_tool_definitions(
            excluded_servers=excluded_servers,
            excluded_tool_names=hot_tool_names,
        )
        tools.extend(active_tools_list)

        data["result"]["tools"] = tools
        hot_count = len(tools) - meta_count
        logger.info(f"Returning {len(tools)} tools ({meta_count} meta + {hot_count} native)")

        # Schedule background cache refresh (non-blocking)
        asyncio.create_task(_refresh_dynamic_mcp_cache(process_manager, docker_tools))

        return data

    # Standard mode: merge HOT tools and apply schema partitioning
    tools = docker_tools

    # Fetch and merge tools from Process MCP servers (HOT only)
    try:
        # Only return HOT server tools (COLD loaded on demand)
        process_tools = await process_manager.list_tools(mode="hot")
        hot_servers = process_manager.get_hot_servers()
        cold_servers = process_manager.get_cold_servers()
        if process_tools:
            logger.info(f"Merging {len(process_tools)} HOT tools with {len(tools)} docker tools")
            logger.info(f"HOT servers: {hot_servers}, COLD servers (not included): {cold_servers}")
            tools.extend(process_tools)
    except Exception as e:
        logger.error(f"Failed to get process tools: {e}")

    partitioned_tools = []

    for tool in tools:
        tool_name = tool.get("name", "")
        input_schema = tool.get("inputSchema", {})

        # Store full schema for expandSchema
        if input_schema:
            schema_partitioner.store_full_schema(tool_name, input_schema)

        full_description = tool.get("description")
        schema_partitioner.store_tool_description(tool_name, full_description)
        # Use configured description mode (default: brief for token optimization)
        lightweight_description = _summarize_description(
            full_description or "",
            mode=settings.DESCRIPTION_MODE
        )

        # Partition schema
        partitioned_schema = schema_partitioner.partition_schema(input_schema)

        # Log token reduction stats
        reduction = schema_partitioner.get_token_reduction_estimate(input_schema)
        logger.debug(f" {tool_name}: {reduction['full']} → {reduction['partitioned']} tokens ({reduction['reduction']}% reduction)")

        extensions = dict(tool.get("extensions", {}))
        if full_description:
            extensions["hasDocs"] = True
            extensions["docHandle"] = tool_name
            extensions["docHint"] = "Call expandSchema with mode='docs' for the full instructions."
        else:
            extensions["hasDocs"] = False

        partitioned_tool = {
            **tool,
            "inputSchema": partitioned_schema,
            "extensions": extensions
        }

        # Handle description based on mode
        if settings.DESCRIPTION_MODE == DescriptionMode.NONE:
            # Remove description entirely for maximum token savings
            partitioned_tool.pop("description", None)
        elif lightweight_description:
            partitioned_tool["description"] = lightweight_description

        partitioned_tools.append(partitioned_tool)

    # Add expandSchema tool
    expand_schema_tool = {
        "name": "expandSchema",
        "description": "Lazy-load schemas or documentation for a specific tool. Use mode='schema' (default) for JSON schema or mode='docs' for the full description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "toolName": {
                    "type": "string",
                    "description": "Name of the tool whose schema or docs you want to expand"
                },
                "path": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Path to the property to expand (e.g., ['metadata', 'shipping']). Omit for full schema."
                },
                "mode": {
                    "type": "string",
                    "enum": ["schema", "docs"],
                    "description": "schema → return JSON schema (default). docs → return stored description text."
                }
            },
            "required": ["toolName"]
        }
    }
    partitioned_tools.append(expand_schema_tool)

    data["result"]["tools"] = partitioned_tools
    return data


def _build_gateway_jsonrpc_url(request: Request) -> str:
    """
    Construct the MCP Gateway URL that matches the client's requested path/query.
    """
    base_url = settings.MCP_GATEWAY_URL.rstrip("/")
    prefix = f"{settings.API_V1_PREFIX}/mcp"
    path = request.url.path

    suffix = path
    if prefix and path.startswith(prefix):
        suffix = path[len(prefix):]

    if not suffix:
        suffix = "/"
    elif not suffix.startswith("/"):
        suffix = f"/{suffix}"

    if request.url.query:
        return f"{base_url}{suffix}?{request.url.query}"
    return f"{base_url}{suffix}"


def _build_gateway_sse_url(request: Request) -> str:
    """
    Construct the MCP Gateway SSE URL, preserving client-provided query params.
    """
    base_url = f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse"
    if request.url.query:
        return f"{base_url}?{request.url.query}"
    return base_url


def _build_stream_gateway_url(request: Request, include_api_prefix: bool = True) -> str:
    """
    Construct the streaming MCP Gateway URL (Codex RMCP transport).
    """
    base_url = settings.MCP_STREAM_GATEWAY_URL.rstrip("/")
    suffix = request.url.path
    prefix = f"{settings.API_V1_PREFIX}/mcp" if include_api_prefix else ""

    if prefix and suffix.startswith(prefix):
        suffix = suffix[len(prefix):]

    if not suffix:
        return base_url if not request.url.query else f"{base_url}?{request.url.query}"

    if not suffix.startswith("/"):
        suffix = f"/{suffix}"

    if request.url.query:
        return f"{base_url}{suffix}?{request.url.query}"
    return f"{base_url}{suffix}"


def _normalize_stream_accept_header(accept_header: Optional[str]) -> str:
    """
    Ensure the upstream stream gateway always receives Accept headers that
    declare both JSON (for Codex logging) and SSE (required by streamable_http).
    """
    required_media_types = ("application/json", "text/event-stream")

    if not accept_header:
        return ", ".join(required_media_types)

    parts: list[str] = []
    seen_tokens: set[str] = set()

    for raw_part in accept_header.split(","):
        part = raw_part.strip()
        if not part:
            continue
        token = part.split(";", 1)[0].strip().lower()
        parts.append(part)
        seen_tokens.add(token)

    for media_type in required_media_types:
        if media_type not in seen_tokens:
            parts.append(media_type)
            seen_tokens.add(media_type)

    return ", ".join(parts)


def _filter_stream_headers(headers: dict[str, str]) -> dict[str, str]:
    """
    Remove hop-by-hop headers that should not be forwarded and normalize Accept.
    """
    blocked = {"host", "content-length", "accept-encoding", "connection", "accept"}
    accept_header = next(
        (value for key, value in headers.items() if key.lower() == "accept"),
        None,
    )
    filtered = {
        key: value
        for key, value in headers.items()
        if key.lower() not in blocked
    }

    filtered["accept"] = _normalize_stream_accept_header(accept_header)

    return filtered


def _format_sse_event(data: Dict[str, Any], event_type: str | None = "message") -> bytes:
    """
    Encode an SSE event payload.
    """
    lines = []
    if event_type:
        lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data)}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _parse_sse_json(lines: list[str]) -> Optional[Dict[str, Any]]:
    """
    Extract JSON payload from SSE event lines.
    """
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    data_str = "\n".join(data_lines)
    try:
        return json.loads(data_str)
    except json.JSONDecodeError:
        return None


def _method_has_body(method: str) -> bool:
    return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


async def _proxy_streaming_gateway_request(
    request: Request,
    *,
    include_api_prefix: bool = True,
    initialize_request_id: Optional[Any] = None,
) -> Response:
    """
    Proxy Codex RMCP streamable_http traffic to the streaming gateway.
    """
    target_url = _build_stream_gateway_url(request, include_api_prefix=include_api_prefix)
    method = request.method.upper()
    payload = await request.body() if _method_has_body(method) else None

    # Use context manager pattern to ensure cleanup in all code paths
    client = httpx.AsyncClient(timeout=STREAM_TIMEOUT)
    upstream = None
    try:
        upstream_request = client.build_request(
            method,
            target_url,
            headers=_filter_stream_headers(dict(request.headers)),
            content=payload,
        )
        upstream = await client.send(upstream_request, stream=True, follow_redirects=True)

        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in {"transfer-encoding", "connection"}
        }

        if method == "HEAD":
            await upstream.aread()
            await upstream.aclose()
            await client.aclose()
            return Response(
                status_code=upstream.status_code,
                headers=response_headers,
            )

        content_type = response_headers.get("content-type", "")
        is_sse_response = "text/event-stream" in content_type.lower()

        async def _inject_initialized_notifications():
            """
            Yield SSE stream chunks and append notifications/initialized when needed.
            """
            if not is_sse_response:
                async for chunk in upstream.aiter_raw():
                    yield chunk
                return

            pending_lines: list[str] = []
            tracked_initialize_id = initialize_request_id

            def flush_lines() -> list[bytes]:
                nonlocal pending_lines, tracked_initialize_id
                if not pending_lines:
                    return [b"\n"]

                event_text = "\n".join(pending_lines)
                payload = _parse_sse_json(pending_lines)
                chunks = [(event_text + "\n\n").encode("utf-8")]

                if isinstance(payload, dict):
                    method = payload.get("method")
                    if method == "notifications/initialized":
                        tracked_initialize_id = None
                    elif (
                        tracked_initialize_id is not None
                        and payload.get("id") == tracked_initialize_id
                        and "result" in payload
                    ):
                        chunks.append(
                            _format_sse_event(
                                {
                                    "jsonrpc": "2.0",
                                    "method": "notifications/initialized",
                                }
                            )
                        )
                        tracked_initialize_id = None

                pending_lines = []
                return chunks

            async for line in upstream.aiter_lines():
                if line == "":
                    for chunk in flush_lines():
                        yield chunk
                else:
                    pending_lines.append(line)

            if pending_lines:
                for chunk in flush_lines():
                    yield chunk

        async def stream_body():
            try:
                async for chunk in _inject_initialized_notifications():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        # Successfully created response - ownership transfers to StreamingResponse
        # The stream_body() finally block will handle cleanup
        return StreamingResponse(
            stream_body(),
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=upstream.headers.get("content-type"),
        )
    except Exception:
        # Cleanup on any failure before StreamingResponse is returned
        if upstream is not None:
            await upstream.aclose()
        await client.aclose()
        raise


def _should_stream_sse(request: Request) -> bool:
    """
    Determine whether the client expects an SSE response.
    """
    accept_header = request.headers.get("accept")
    if not accept_header:
        return False
    return "text/event-stream" in accept_header.lower()


def _build_sse_response(request: Request) -> StreamingResponse:
    """
    Return a StreamingResponse for MCP SSE proxy traffic.
    """
    return StreamingResponse(
        proxy_sse_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering at the edge
        }
    )


@router.get("/sse")
async def mcp_sse_proxy(request: Request):
    """
    MCP SSE Proxy Endpoint

    Claude Code connects via the public API URL (`${GATEWAY_API_URL}/v1/mcp/sse`)
    """
    return _build_sse_response(request)


async def _proxy_jsonrpc_request(request: Request) -> Response:
    """
    MCP JSON-RPC 2.0 Proxy Endpoint（tools/call用）

    Args:
        request: JSON-RPC 2.0 リクエスト

    Returns:
        JSON-RPC 2.0 レスポンス
    """
    body = await request.body()
    rpc_request = json.loads(body)
    method = rpc_request.get("method") if isinstance(rpc_request, dict) else None
    is_initialize_request = method == "initialize"
    session_id = request.query_params.get("sessionid")

    logger.info(f"JSON-RPC request: method={method}, sessionid={session_id}")

    # Auto-initialize session if tools/call arrives for uninitialized session
    # This is a fallback for clients that don't follow proper MCP init sequence
    if method == "tools/call" and session_id and session_id not in _initialized_sessions:
        logger.info(f"Session {session_id} not initialized, running init sequence")
        gateway_post_url = f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse?sessionid={session_id}"

        async with httpx.AsyncClient(timeout=INIT_CLIENT_TIMEOUT) as init_client:
            try:
                # Step 1: Send initialize request
                initialize_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "airis-proxy",
                            "version": "1.0.0"
                        }
                    }
                }
                init_response = await init_client.post(
                    gateway_post_url,
                    json=initialize_request,
                    headers={"Content-Type": "application/json"}
                )

                # SSE transport returns 202 Accepted for successful POST
                if init_response.status_code not in (200, 202):
                    logger.error(f"Initialize request failed: {init_response.status_code}")
                    # Continue anyway - let the actual request fail with proper error
                else:
                    logger.info(f"Initialize request accepted: {init_response.status_code}")

                    # Wait for Gateway to process initialize request
                    # This delay is critical - Gateway needs time to set up session state
                    await asyncio.sleep(0.15)

                    # Step 2: Send notifications/initialized
                    # Per MCP spec, this should come after initialize response, but in SSE transport
                    # the response comes via stream. Gateway accepts this sequence for recovery.
                    initialized_notification = {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized"
                    }
                    notif_response = await init_client.post(
                        gateway_post_url,
                        json=initialized_notification,
                        headers={"Content-Type": "application/json"}
                    )

                    if notif_response.status_code in (200, 202):
                        # Wait for Gateway to complete initialization before allowing tools/call
                        await asyncio.sleep(0.10)
                        _initialized_sessions.add(session_id)
                        logger.info(f"Session {session_id} initialized successfully")
                    else:
                        logger.error(f"Initialized notification failed: {notif_response.status_code}")

            except httpx.TimeoutException:
                logger.info(f"Init sequence timed out for session {session_id}")
            except Exception as e:
                logger.error(f"Init sequence failed: {e}")

    # Handle expandSchema tool call
    if rpc_request.get("method") == "tools/call":
        params = rpc_request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "expandSchema":
            # Handle locally, do not proxy to Gateway
            return await handle_expand_schema(rpc_request)

        # Dynamic MCP meta-tools (only when DYNAMIC_MCP=true)
        if tool_name == "airis-activate":
            return await handle_airis_activate(rpc_request, session_id=session_id)

        if tool_name == "airis-find":
            return await handle_airis_find(rpc_request, session_id=session_id)

        if tool_name == "airis-exec":
            return await handle_airis_exec(rpc_request, session_id=session_id)

        if tool_name == "airis-schema":
            return await handle_airis_schema(rpc_request, session_id=session_id)

        if tool_name == "airis-confidence":
            return await handle_airis_confidence(rpc_request, session_id=session_id)

        if tool_name == "airis-repo-index":
            return await handle_airis_repo_index(rpc_request, session_id=session_id)

        if tool_name == "airis-suggest":
            return await handle_airis_suggest(rpc_request, session_id=session_id)

        if tool_name == "airis-route":
            return await handle_airis_route(rpc_request, session_id=session_id)

    # Handle prompts/get request
    if rpc_request.get("method") == "prompts/get":
        params = rpc_request.get("params", {})
        prompt_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # Try Process MCP servers first
        # (get_prompt searches active servers even without cache)
        try:
            process_manager = get_process_manager()
            logger.info(f"Trying ProcessManager for prompt: {prompt_name}")
            server_response = await process_manager.get_prompt(prompt_name, arguments)

            # Fall back to Docker Gateway if prompt not found
            if "error" in server_response and server_response["error"].get("code") == -32601:
                logger.info(f"Prompt {prompt_name} not found in ProcessManager, falling through to Gateway")
            else:
                # Build JSON-RPC response using client's request ID
                response_data = {
                    "jsonrpc": "2.0",
                    "id": rpc_request.get("id"),
                }
                # Extract result or error from server response
                if "error" in server_response:
                    response_data["error"] = server_response["error"]
                else:
                    response_data["result"] = server_response.get("result")

                # MCP SSE Transport: send response via SSE stream
                if session_id:
                    queue = await get_response_queue(session_id)
                    await queue.put(response_data)
                    logger.info(f"Queued prompts/get response for session {session_id}")
                    return Response(status_code=202)

                # Fallback to HTTP response when no sessionid
                return Response(
                    content=json.dumps(response_data),
                    status_code=200,
                    media_type="application/json"
                )
        except Exception as e:
            logger.error(f"ProcessManager prompt routing failed: {e}")

    # Handle tools/call request
    if rpc_request.get("method") == "tools/call":
        params = rpc_request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # Check if tool belongs to a Process MCP server
        try:
            process_manager = get_process_manager()
            # Check if tool name is registered in ProcessManager
            if tool_name in process_manager._tool_to_server:
                logger.info(f"Routing {tool_name} to ProcessManager")
                server_response = await process_manager.call_tool(tool_name, arguments)
                # Build JSON-RPC response using client's request ID
                response_data = {
                    "jsonrpc": "2.0",
                    "id": rpc_request.get("id"),
                }
                # Extract result or error from server response
                if "error" in server_response:
                    response_data["error"] = server_response["error"]
                else:
                    response_data["result"] = server_response.get("result")

                # MCP SSE Transport: send response via SSE stream
                if session_id:
                    queue = await get_response_queue(session_id)
                    await queue.put(response_data)
                    logger.info(f"Queued tools/call response for session {session_id}")
                    return Response(status_code=202)

                # Fallback to HTTP response when no sessionid
                return Response(
                    content=json.dumps(response_data),
                    status_code=200,
                    media_type="application/json"
                )
        except Exception as e:
            logger.error(f"ProcessManager routing check failed: {e}")

    # Proxy all other tool calls to Gateway
    if not session_id:
        # Streamable HTTP clients (Codex) are bridged onto the existing SSE backend.
        return await _send_via_stream_bridge(request, rpc_request)

    target_url = _build_gateway_jsonrpc_url(request)
    forward_headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("Authorization")
    if auth_header:
        forward_headers["Authorization"] = auth_header

    # Use configurable timeout (default: 90s) to prevent Claude Code hanging
    async with httpx.AsyncClient(timeout=get_jsonrpc_timeout()) as client:
        response = await client.post(
            target_url,
            content=body,
            headers=forward_headers,
            follow_redirects=True,
        )

        # On successful initialize, send notifications/initialized to Gateway
        if is_initialize_request and response.status_code in (200, 202):
            logger.info(f"Initialize request successful, sending initialized notification to Gateway (sessionid={session_id})")
            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }
            gateway_post_url = f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse?sessionid={session_id}"
            try:
                init_response = await client.post(
                    gateway_post_url,
                    json=initialized_notification,
                    headers={"Content-Type": "application/json"}
                )
                logger.info(f"Sent initialized notification: {init_response.status_code}")
            except Exception as e:
                logger.error(f"Failed to send initialized notification: {e}")

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers)
        )


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def mcp_http_health_check():
    """Lightweight health check for Streamable HTTP transport."""
    return {"status": "ok"}


@router.head("", include_in_schema=False)
@router.head("/", include_in_schema=False)
async def mcp_http_health_check_head():
    """HEAD variant for Streamable HTTP transport."""
    return Response(status_code=204)


@router.delete("", include_in_schema=False)
@router.delete("/", include_in_schema=False)
async def mcp_stream_delete(request: Request):
    """Allow Streamable HTTP clients to end a bridged session."""
    return await _delete_stream_bridge_session(request)


@router.post("", include_in_schema=False)
async def mcp_jsonrpc_proxy_root(request: Request):
    """Expose the JSON-RPC proxy at /api/v1/mcp (no trailing slash)."""
    return await _proxy_jsonrpc_request(request)


@router.post("/")
async def mcp_jsonrpc_proxy(request: Request):
    """Expose the JSON-RPC proxy at /api/v1/mcp/."""
    return await _proxy_jsonrpc_request(request)


@router.post("/sse", include_in_schema=False)
async def mcp_sse_proxy_post(request: Request):
    """
    Handle POST requests to /sse endpoint.

    MCP SSE transport:
    - GET /sse → SSE stream (server-initiated messages)
    - POST /sse?sessionid=X → JSON-RPC request/response

    POST requests with sessionid should ALWAYS go through JSON-RPC handler.
    """
    # POST requests with sessionid are JSON-RPC requests - handle them directly
    session_id = request.query_params.get("sessionid")
    if session_id:
        return await _proxy_jsonrpc_request(request)

    # Legacy: POST without sessionid and requesting SSE stream
    if _should_stream_sse(request):
        return _build_sse_response(request)

    return await _proxy_jsonrpc_request(request)


@router.api_route("/.well-known/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def mcp_stream_well_known(request: Request, path: str):
    """
    Forward /.well-known discovery requests under the API prefix.
    """
    return await _proxy_streaming_gateway_request(request)


async def proxy_root_well_known(request: Request, path: str) -> Response:
    """
    Public /.well-known proxy mounted at the application root.
    """
    return await _proxy_streaming_gateway_request(
        request,
        include_api_prefix=False,
    )


async def handle_airis_find(rpc_request: Dict[str, Any], session_id: Optional[str] = None) -> Response:
    """
    airis-find ツールコール: ツール/サーバー検索

    Args:
        rpc_request: JSON-RPC 2.0 リクエスト
        session_id: SSE session ID for response routing

    Returns:
        JSON-RPC 2.0 レスポンス
    """
    params = rpc_request.get("params", {})
    arguments = params.get("arguments", {})

    query = arguments.get("query")
    server = arguments.get("server")

    dynamic_mcp = get_dynamic_mcp()
    process_manager = get_process_manager()
    dynamic_mcp.refresh_toolsets(process_manager)

    from ...core.dynamic_mcp import ToolInfo, ServerInfo

    # Defensive null check
    if dynamic_mcp is None:
        logger.warning("DynamicMCP singleton not initialized")
        return Response(
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
                "error": {"code": -32603, "message": "Dynamic MCP not initialized"}
            }),
            status_code=200,
            media_type="application/json"
        )

    # Always ensure servers are cached (even if tools already exist)
    # This is needed because tools/list populates tools but not necessarily servers
    # Check for process servers specifically (Docker servers may already be pre-cached)
    has_process_servers = any(s.source == "process" for s in dynamic_mcp._servers.values())
    if not has_process_servers:
        logger.info("Server cache empty, refreshing...")
        # Cache server info for ALL servers (including COLD and disabled)
        index_count = 0
        for name in process_manager.get_server_names():
            status = process_manager.get_server_status(name)
            dynamic_mcp._servers[name] = ServerInfo(
                name=name,
                enabled=status.get("enabled", False),
                mode=status.get("mode", "cold"),
                tools_count=status.get("tools_count", 0),
                source="process"
            )
            # Also cache tools_index entries for COLD/disabled servers
            config = process_manager._server_configs.get(name)
            if config and config.tools_index:
                for tool_entry in config.tools_index:
                    tool_name = tool_entry.get("name", "")
                    if tool_name and tool_name not in dynamic_mcp._tools:
                        dynamic_mcp._tools[tool_name] = ToolInfo(
                            name=tool_name,
                            server=name,
                            description=tool_entry.get("description", ""),
                            input_schema={},
                            source="index"
                        )
                        dynamic_mcp._tool_to_server[tool_name] = name
                        index_count += 1

        logger.info(f"Cached {len(dynamic_mcp._servers)} servers, {index_count} tools from index")

    # Auto-refresh ProcessManager tools if not yet cached
    # (Docker Gateway tools may be pre-cached at startup, but we still need ProcessManager tools)
    # Only load HOT servers here - COLD servers are loaded on-demand by smart discovery
    has_process_tools = any(t.source == "process" for t in dynamic_mcp._tools.values())
    if not has_process_tools:
        logger.info("No ProcessManager tools in cache, refreshing from HOT servers...")
        # Load tools from HOT servers only - COLD servers loaded on-demand
        all_tools = await process_manager.list_tools(mode="hot")
        for tool in all_tools:
            tool_name = tool.get("name", "")
            server_name = process_manager._tool_to_server.get(tool_name, "unknown")
            if tool_name:
                dynamic_mcp._tools[tool_name] = ToolInfo(
                    name=tool_name,
                    server=server_name,
                    description=tool.get("description", ""),
                    input_schema=tool.get("inputSchema", {}),
                    source="process"
                )
                dynamic_mcp._tool_to_server[tool_name] = server_name
        logger.info(f"Cached {len(all_tools)} process tools (total: {len(dynamic_mcp._tools)})")

    # If specific server requested and it's a process server, ensure it's in the cache
    if server:
        is_process = process_manager.is_process_server(server)
        server_info = dynamic_mcp._servers.get(server)

        # Add server to cache if it's a process server but not yet cached
        if is_process and not server_info:
            status = process_manager.get_server_status(server)
            dynamic_mcp._servers[server] = ServerInfo(
                name=server,
                enabled=status.get("enabled", False),
                mode=status.get("mode", "cold"),
                tools_count=status.get("tools_count", 0),
                source="process"
            )
            server_info = dynamic_mcp._servers[server]
            logger.info(f"Added server '{server}' to cache (mode={server_info.mode})")

        # If it's a COLD server with no tools cached, start it and cache tools
        # Note: tools_count is metadata, we need to check if tools are actually in _tools dict
        server_has_tools = any(t.server == server for t in dynamic_mcp._tools.values())
        if is_process and server_info and server_info.mode == "cold" and not server_has_tools:
            logger.info(f"Starting COLD server '{server}' to get tools...")
            server_tools = await process_manager._list_tools_for_server(server)
            for tool in server_tools:
                tool_name = tool.get("name", "")
                if tool_name:
                    dynamic_mcp._tools[tool_name] = ToolInfo(
                        name=tool_name,
                        server=server,
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {}),
                        source="process"
                    )
                    dynamic_mcp._tool_to_server[tool_name] = server
            # Update server tools count
            if server in dynamic_mcp._servers:
                dynamic_mcp._servers[server].tools_count = len(server_tools)
            logger.info(f"Loaded {len(server_tools)} tools from '{server}'")

    results = dynamic_mcp.find(query=query, server=server)

    # Format results as text for LLM consumption
    lines = []
    lines.append(f"Found {len(results['tools'])} tools across {results['total_servers']} servers\n")

    if results['servers']:
        lines.append("## Servers")
        for s in results['servers']:
            status = "enabled" if s['enabled'] else "disabled"
            lines.append(f"- **{s['name']}** ({s['mode']}, {status}): {s['tools_count']} tools")
        lines.append("")

    if results.get('toolsets'):
        lines.append("## Toolsets")
        for toolset in results['toolsets']:
            lines.append(f"- **{toolset['ref']}** - {toolset['summary']} ({toolset['tools_count']} tools)")
        lines.append("")

    if results['tools']:
        lines.append("## Tools")
        for t in results['tools']:
            lines.append(f"- **{t['server']}:{t['name']}** - {t['description']}")

    if not results['tools'] and not results['servers'] and not results.get('toolsets'):
        lines.append("No matches found. Try a different query or use airis-find without arguments to list all.")
        # Show hint about available COLD servers
        if not server:
            cold_servers = process_manager.get_cold_servers()
            enabled_cold = [s for s in cold_servers if s in process_manager.get_enabled_servers()]
            if enabled_cold:
                lines.append(f"\nTip: COLD servers available: {', '.join(enabled_cold)}")
                lines.append("Use `server` parameter to load specific server, e.g., airis-find server=\"tavily\"")

    response_text = "\n".join(lines)

    response_data = {
        "jsonrpc": "2.0",
        "id": rpc_request.get("id"),
        "result": {
            "content": [{"type": "text", "text": response_text}]
        }
    }

    # MCP SSE Transport: Response via SSE stream
    if session_id:
        queue = await get_response_queue(session_id)
        await queue.put(response_data)
        logger.info(f"Queued airis-find response for session {session_id}")
        return Response(status_code=202)

    # Fallback to HTTP response if no session_id
    return Response(
        content=json.dumps(response_data),
        status_code=200,
        media_type="application/json"
    )


async def handle_airis_activate(rpc_request: Dict[str, Any], session_id: Optional[str] = None) -> Response:
    """
    Activate a toolset so its native tools appear in tools/list and can be called directly.
    """
    params = rpc_request.get("params", {})
    arguments = params.get("arguments", {})
    toolset_ref = arguments.get("toolset")

    if not toolset_ref:
        error_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {"code": -32602, "message": "toolset is required"}
        }
        if session_id:
            queue = await get_response_queue(session_id)
            await queue.put(error_data)
            return Response(status_code=202)
        return Response(
            content=json.dumps(error_data),
            status_code=200,
            media_type="application/json"
        )

    dynamic_mcp = get_dynamic_mcp()
    process_manager = get_process_manager()
    dynamic_mcp.refresh_toolsets(process_manager)
    result = await dynamic_mcp.activate_toolset(toolset_ref, process_manager)

    if not result.get("ok"):
        error_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {"code": -32602, "message": result["message"]}
        }
        if session_id:
            queue = await get_response_queue(session_id)
            await queue.put(error_data)
            return Response(status_code=202)
        return Response(
            content=json.dumps(error_data),
            status_code=200,
            media_type="application/json"
        )

    lines = [
        f"Activated {len(result['toolsets'])} toolset(s).",
        "",
        "## Toolsets",
    ]
    for ref in result["toolsets"]:
        lines.append(f"- **{ref}**")

    if result["servers"]:
        lines.extend(["", "## Enabled Servers"])
        for name in result["servers"]:
            lines.append(f"- **{name}**")

    if result["tools"]:
        lines.extend(["", "## Native Tools Now Available"])
        for tool_name in result["tools"]:
            server_name = dynamic_mcp.get_server_for_tool(tool_name) or "unknown"
            lines.append(f"- **{server_name}:{tool_name}**")

    lines.extend([
        "",
        "Call the native MCP tool directly after the client refreshes tools/list."
    ])

    response_data = {
        "jsonrpc": "2.0",
        "id": rpc_request.get("id"),
        "result": {
            "content": [{"type": "text", "text": "\n".join(lines)}]
        }
    }

    if session_id:
        queue = await get_response_queue(session_id)
        await queue.put(response_data)
        await queue.put({
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed"
        })
        logger.info(f"Queued airis-activate response for session {session_id}")
        return Response(status_code=202)

    return Response(
        content=json.dumps(response_data),
        status_code=200,
        media_type="application/json"
    )


async def handle_airis_exec(rpc_request: Dict[str, Any], session_id: Optional[str] = None) -> Response:
    """
    airis-exec ツールコール: 任意のツールを実行

    Args:
        rpc_request: JSON-RPC 2.0 リクエスト
        session_id: SSEセッションID（レスポンスキュー用）

    Returns:
        JSON-RPC 2.0 レスポンス
    """
    params = rpc_request.get("params", {})
    arguments = params.get("arguments", {})

    tool_ref = arguments.get("tool")
    tool_args = arguments.get("arguments", {})
    # Handle string-encoded JSON arguments (Claude Code may send "{}" instead of {})
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse string arguments: {tool_args[:100]}")
            tool_args = {}

    if not tool_ref:
        return Response(
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
                "error": {"code": -32602, "message": "tool is required"}
            }),
            status_code=200,
            media_type="application/json"
        )

    dynamic_mcp = get_dynamic_mcp()
    server_name, tool_name = dynamic_mcp.parse_tool_reference(tool_ref)

    logger.info(f"airis-exec: {tool_ref} -> server={server_name}, tool={tool_name}")

    process_manager = get_process_manager()

    # Auto-discovery: if tool not in cache, try tools_index to find the server
    if not server_name:
        server_name = dynamic_mcp.get_server_for_tool_from_index(tool_name, process_manager)
        if server_name:
            logger.info(f"Auto-discovered tool '{tool_name}' on server '{server_name}' via tools_index")

    if not server_name:
        return Response(
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
                "error": {
                    "code": -32601,
                    "message": f"Tool not found: {tool_ref}. Use airis-find to discover available tools."
                }
            }),
            status_code=200,
            media_type="application/json"
        )
    if process_manager.is_process_server(server_name):
        config = process_manager._server_configs.get(server_name)

        # Auto-enable COLD mode servers on first airis-exec call
        if config and config.mode == ServerMode.COLD and not config.enabled:
            logger.info(f"Auto-enabling COLD server for airis-exec: {server_name}")
            await process_manager.enable_server(server_name)

        # Execute if server is now enabled
        if config and config.enabled:
            result = await process_manager.call_tool_on_server(server_name, tool_name, tool_args)

            response_data = {
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
            }
            if "error" in result:
                error_msg = result["error"].get("message", "")
                # Attach schema hint so LLM can retry with correct arguments
                schema_hint = None
                tool_info = dynamic_mcp._tools.get(tool_name)
                if tool_info and tool_info.input_schema:
                    schema_hint = tool_info.input_schema
                elif not tool_info:
                    await dynamic_mcp.load_tools_for_server(server_name, process_manager)
                    tool_info = dynamic_mcp._tools.get(tool_name)
                    if tool_info and tool_info.input_schema:
                        schema_hint = tool_info.input_schema

                if schema_hint:
                    response_data["result"] = {
                        "content": [{
                            "type": "text",
                            "text": f"Error: {error_msg}\n\nExpected schema:\n{json.dumps(schema_hint, indent=2)}"
                        }],
                        "isError": True
                    }
                else:
                    response_data["error"] = result["error"]
            else:
                response_data["result"] = result.get("result")

            # Send via SSE queue if session exists
            if session_id:
                queue = await get_response_queue(session_id)
                await queue.put(response_data)
                return Response(status_code=202)

            return Response(
                content=json.dumps(response_data),
                status_code=200,
                media_type="application/json"
            )

    # Route to Docker Gateway for non-process tools
    # Check if we have a session to proxy through
    if not session_id:
        return Response(
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Cannot execute Docker gateway tool without session: {tool_ref}"
                }
            }),
            status_code=200,
            media_type="application/json"
        )

    # Build tools/call request for Docker Gateway
    gateway_request = {
        "jsonrpc": "2.0",
        "id": rpc_request.get("id"),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": tool_args
        }
    }

    gateway_post_url = f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse?sessionid={session_id}"
    logger.info(f"Proxying airis-exec to Docker Gateway: {tool_name}")

    try:
        # Use configurable timeout (default: 90s) to prevent Claude Code hanging
        async with httpx.AsyncClient(timeout=get_jsonrpc_timeout()) as client:
            response = await client.post(
                gateway_post_url,
                json=gateway_request,
                headers={"Content-Type": "application/json"}
            )

            # SSE transport returns 202 Accepted, actual response comes via SSE stream
            if response.status_code == 202:
                # Response will come through SSE - return accepted
                return Response(status_code=202)

            # Direct response (shouldn't happen with SSE transport, but handle it)
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type="application/json"
            )
    except httpx.TimeoutException:
        return Response(
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Docker gateway timeout ({settings.TOOL_CALL_TIMEOUT}s) for tool: {tool_ref}"
                }
            }),
            status_code=200,
            media_type="application/json"
        )
    except Exception as e:
        return Response(
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Docker gateway error: {str(e)}"
                }
            }),
            status_code=200,
            media_type="application/json"
        )


async def handle_airis_schema(rpc_request: Dict[str, Any], session_id: Optional[str] = None) -> Response:
    """
    airis-schema ツールコール: ツールのスキーマを取得

    Args:
        rpc_request: JSON-RPC 2.0 リクエスト
        session_id: SSE session ID for response routing

    Returns:
        JSON-RPC 2.0 レスポンス
    """
    params = rpc_request.get("params", {})
    arguments = params.get("arguments", {})

    tool_ref = arguments.get("tool")

    if not tool_ref:
        error_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {"code": -32602, "message": "tool is required"}
        }
        if session_id:
            queue = await get_response_queue(session_id)
            await queue.put(error_data)
            return Response(status_code=202)
        return Response(
            content=json.dumps(error_data),
            status_code=200,
            media_type="application/json"
        )

    # Parse tool reference
    dynamic_mcp = get_dynamic_mcp()
    _, tool_name = dynamic_mcp.parse_tool_reference(tool_ref)

    # Get schema from cache
    schema = dynamic_mcp.get_tool_schema(tool_name)
    if not schema:
        # Try schema_partitioner as fallback
        full_schema = schema_partitioner.expand_schema(tool_name, None)
        description = schema_partitioner.get_tool_description(tool_name)
        if full_schema:
            schema = {
                "name": tool_name,
                "description": description or "",
                "inputSchema": full_schema
            }

    # Auto-discovery: if schema not found, try loading from tools_index server
    if not schema:
        process_manager = get_process_manager()
        server_name = dynamic_mcp.get_server_for_tool_from_index(tool_name, process_manager)
        if server_name:
            logger.info(f"Auto-loading schema for '{tool_name}' from server '{server_name}'")
            tools = await dynamic_mcp.load_tools_for_server(server_name, process_manager, force_enable=True)
            schema = dynamic_mcp.get_tool_schema(tool_name)

    if not schema:
        error_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {
                "code": -32602,
                "message": f"Schema not found for tool: {tool_ref}. Use airis-find to discover available tools."
            }
        }
        if session_id:
            queue = await get_response_queue(session_id)
            await queue.put(error_data)
            return Response(status_code=202)
        return Response(
            content=json.dumps(error_data),
            status_code=200,
            media_type="application/json"
        )

    # Format schema as readable text
    lines = [
        f"# {schema['name']}",
        "",
        f"**Server:** {schema.get('server', 'unknown')}",
        "",
        f"**Description:** {schema.get('description', 'No description')}",
        "",
        "## Input Schema",
        "```json",
        json.dumps(schema.get("inputSchema", {}), indent=2),
        "```"
    ]

    response_data = {
        "jsonrpc": "2.0",
        "id": rpc_request.get("id"),
        "result": {
            "content": [{"type": "text", "text": "\n".join(lines)}]
        }
    }

    # MCP SSE Transport: Response via SSE stream
    if session_id:
        queue = await get_response_queue(session_id)
        await queue.put(response_data)
        logger.info(f"Queued airis-schema response for session {session_id}")
        return Response(status_code=202)

    # Fallback to HTTP response if no session_id
    return Response(
        content=json.dumps(response_data),
        status_code=200,
        media_type="application/json"
    )


async def handle_expand_schema(rpc_request: Dict[str, Any]) -> Response:
    """
    expandSchema ツールコールをローカル処理

    Args:
        rpc_request: JSON-RPC 2.0 リクエスト

    Returns:
        JSON-RPC 2.0 レスポンス (Response object)
    """
    params = rpc_request.get("params", {})
    arguments = params.get("arguments", {})

    tool_name = arguments.get("toolName")
    path = arguments.get("path")
    mode = arguments.get("mode", "schema")

    # Log expandSchema request
    await protocol_logger.log_message("client→server", rpc_request, {
        "phase": "expand_schema",
        "tool_name": tool_name
    })

    if not tool_name:
        error_response = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {
                "code": -32602,
                "message": "toolName is required"
            }
        }
        await protocol_logger.log_message("server→client", error_response, {
            "phase": "expand_schema",
            "tool_name": tool_name
        })
        return Response(
            content=json.dumps(error_response),
            status_code=200,
            media_type="application/json"
        )

    if mode not in {"schema", "docs"}:
        error_response = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {
                "code": -32602,
                "message": "mode must be 'schema' or 'docs'"
            }
        }
        await protocol_logger.log_message("server→client", error_response, {
            "phase": "expand_schema",
            "tool_name": tool_name
        })
        return Response(
            content=json.dumps(error_response),
            status_code=200,
            media_type="application/json"
        )

    if mode == "docs":
        detailed_description = schema_partitioner.get_tool_description(tool_name)
        if not detailed_description:
            error_response = {
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
                "error": {
                    "code": -32602,
                    "message": f"Documentation not found for tool: {tool_name}"
                }
            }
            await protocol_logger.log_message("server→client", error_response, {
                "phase": "expand_schema",
                "tool_name": tool_name
            })
            return Response(
                content=json.dumps(error_response),
                status_code=200,
                media_type="application/json"
            )

        response_content = detailed_description
    else:
        # Retrieve the requested path from full schema
        expanded_schema = schema_partitioner.expand_schema(tool_name, path)

        if expanded_schema is None:
            error_response = {
                "jsonrpc": "2.0",
                "id": rpc_request.get("id"),
                "error": {
                    "code": -32602,
                    "message": f"Schema not found for tool: {tool_name}"
                }
            }
            await protocol_logger.log_message("server→client", error_response, {
                "phase": "expand_schema",
                "tool_name": tool_name
            })
            return Response(
                content=json.dumps(error_response),
                status_code=200,
                media_type="application/json"
            )

        response_content = json.dumps(expanded_schema, indent=2)

    success_response = {
        "jsonrpc": "2.0",
        "id": rpc_request.get("id"),
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": response_content
                }
            ]
        }
    }

    # Log expandSchema response
    await protocol_logger.log_message("server→client", success_response, {
        "phase": "expand_schema",
        "tool_name": tool_name
    })

    return Response(
        content=json.dumps(success_response),
        status_code=200,
        media_type="application/json"
    )


async def handle_airis_confidence(rpc_request: Dict[str, Any], session_id: Optional[str] = None) -> Response:
    """
    airis-confidence: Pre-implementation confidence check

    Args:
        rpc_request: JSON-RPC 2.0 request
        session_id: SSE session ID for response routing

    Returns:
        JSON-RPC 2.0 response
    """
    from ...core.confidence_engine import ConfidenceInput, get_confidence_checker

    params = rpc_request.get("params", {})
    arguments = params.get("arguments", {})

    # Build ConfidenceInput from arguments
    input_data = ConfidenceInput(
        task=arguments.get("task", ""),
        has_official_docs=arguments.get("has_official_docs", False),
        has_existing_patterns=arguments.get("has_existing_patterns", False),
        has_clear_path=arguments.get("has_clear_path", False),
        multiple_approaches=arguments.get("multiple_approaches", False),
        has_trade_offs=arguments.get("has_trade_offs", False),
        unclear_requirements=arguments.get("unclear_requirements", False),
        no_precedent=arguments.get("no_precedent", False),
        missing_domain_knowledge=arguments.get("missing_domain_knowledge", False),
    )

    checker = get_confidence_checker()
    result = checker.assess(input_data)

    # Format result as readable text
    lines = [
        f"# Confidence Assessment",
        "",
        f"**Score:** {int(result.score * 100)}% ({result.level})",
        f"**Verdict:** {result.verdict.value}",
        f"**Should Proceed:** {'Yes' if result.should_proceed else 'No'}",
        "",
        "## Reasons",
    ]

    for reason in result.reasons:
        lines.append(f"- {reason}")

    if result.questions:
        lines.append("")
        lines.append("## Clarifying Questions")
        for q in result.questions:
            lines.append(f"- {q}")

    lines.append("")
    lines.append("## Recommendation")
    lines.append(checker.get_recommendation(result.score))

    response_text = "\n".join(lines)

    response_data = {
        "jsonrpc": "2.0",
        "id": rpc_request.get("id"),
        "result": {
            "content": [{"type": "text", "text": response_text}]
        }
    }

    # MCP SSE Transport: Response via SSE stream
    if session_id:
        queue = await get_response_queue(session_id)
        await queue.put(response_data)
        logger.info(f"Queued airis-confidence response for session {session_id}")
        return Response(status_code=202)

    return Response(
        content=json.dumps(response_data),
        status_code=200,
        media_type="application/json"
    )


async def handle_airis_repo_index(rpc_request: Dict[str, Any], session_id: Optional[str] = None) -> Response:
    """
    airis-repo-index: Generate repository index

    Args:
        rpc_request: JSON-RPC 2.0 request
        session_id: SSE session ID for response routing

    Returns:
        JSON-RPC 2.0 response
    """
    from ...core.repo_indexer import RepoIndexRequest, generate_repo_index

    params = rpc_request.get("params", {})
    arguments = params.get("arguments", {})

    repo_path = arguments.get("repo_path")
    if not repo_path:
        error_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {"code": -32602, "message": "repo_path is required"}
        }
        if session_id:
            queue = await get_response_queue(session_id)
            await queue.put(error_data)
            return Response(status_code=202)
        return Response(
            content=json.dumps(error_data),
            status_code=200,
            media_type="application/json"
        )

    try:
        request = RepoIndexRequest(
            repo_path=repo_path,
            mode=arguments.get("mode", "full"),
            include_docs=arguments.get("include_docs", True),
            include_tests=arguments.get("include_tests", True),
            max_entries=arguments.get("max_entries", 10),
        )
        result = generate_repo_index(request)

        response_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "result": {
                "content": [{"type": "text", "text": result.markdown}]
            }
        }

    except FileNotFoundError as e:
        response_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {"code": -32602, "message": str(e)}
        }
    except Exception as e:
        logger.error(f"airis-repo-index failed: {e}")
        response_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {"code": -32603, "message": f"Indexing failed: {str(e)}"}
        }

    # MCP SSE Transport: Response via SSE stream
    if session_id:
        queue = await get_response_queue(session_id)
        await queue.put(response_data)
        logger.info(f"Queued airis-repo-index response for session {session_id}")
        return Response(status_code=202)

    return Response(
        content=json.dumps(response_data),
        status_code=200,
        media_type="application/json"
    )


async def handle_airis_suggest(rpc_request: Dict[str, Any], session_id: Optional[str] = None) -> Response:
    """
    airis-suggest: Suggest MCP tools based on natural language intent

    Args:
        rpc_request: JSON-RPC 2.0 request
        session_id: SSE session ID for response routing

    Returns:
        JSON-RPC 2.0 response
    """
    from ...core.tool_suggester import SuggestToolRequest, suggest_tool, format_suggestions_as_text

    params = rpc_request.get("params", {})
    arguments = params.get("arguments", {})

    intent = arguments.get("intent")
    if not intent:
        error_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {"code": -32602, "message": "intent is required"}
        }
        if session_id:
            queue = await get_response_queue(session_id)
            await queue.put(error_data)
            return Response(status_code=202)
        return Response(
            content=json.dumps(error_data),
            status_code=200,
            media_type="application/json"
        )

    # Get DynamicMCP instance for live tool lookup
    dynamic_mcp = get_dynamic_mcp()

    request = SuggestToolRequest(
        intent=intent,
        max_results=arguments.get("max_results", 5),
    )
    result = suggest_tool(request, dynamic_mcp=dynamic_mcp)

    response_text = format_suggestions_as_text(result)

    response_data = {
        "jsonrpc": "2.0",
        "id": rpc_request.get("id"),
        "result": {
            "content": [{"type": "text", "text": response_text}]
        }
    }

    # MCP SSE Transport: Response via SSE stream
    if session_id:
        queue = await get_response_queue(session_id)
        await queue.put(response_data)
        logger.info(f"Queued airis-suggest response for session {session_id}")
        return Response(status_code=202)

    return Response(
        content=json.dumps(response_data),
        status_code=200,
        media_type="application/json"
    )


async def handle_airis_route(rpc_request: Dict[str, Any], session_id: Optional[str] = None) -> Response:
    """
    airis-route: Route a task to the optimal tool chain.

    Args:
        rpc_request: JSON-RPC 2.0 request
        session_id: SSE session ID for response routing

    Returns:
        JSON-RPC 2.0 response
    """
    from ...core.routing_engine import load_routing_table, route_task

    params = rpc_request.get("params", {}).get("arguments", {})
    task = params.get("task", "")
    max_results = params.get("max_results", 5)

    if not task:
        response_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "error": {"code": -32602, "message": "Missing required parameter: task"}
        }
    else:
        dynamic_mcp = get_dynamic_mcp()
        routing_table = load_routing_table()
        result = route_task(
            task=task,
            routing_table=routing_table,
            dynamic_mcp=dynamic_mcp,
            max_results=max_results,
        )

        # Format as readable text
        lines = []
        if result.chain:
            lines.append(f"## Route: {result.hint}")
            lines.append(f"Chain: {' → '.join(result.chain)}")
            lines.append(f"Pattern: `{result.pattern}`")
        else:
            lines.append("## No direct route found")
            lines.append("Falling back to tool suggestions.")

        if result.suggestions:
            lines.append("")
            lines.append("## Suggested Tools")
            for i, s in enumerate(result.suggestions, 1):
                score_pct = int(s["score"] * 100)
                lines.append(f"{i}. **{s['server']}:{s['tool']}** ({score_pct}%) — {s['reason']}")

        lines.append("")
        lines.append("Use `airis-exec` to execute tools in the chain.")

        response_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
            "result": {
                "content": [{"type": "text", "text": "\n".join(lines)}]
            }
        }

    # MCP SSE Transport: Response via SSE stream
    if session_id:
        queue = await get_response_queue(session_id)
        await queue.put(response_data)
        logger.info(f"Queued airis-route response for session {session_id}")
        return Response(status_code=202)

    return Response(
        content=json.dumps(response_data),
        status_code=200,
        media_type="application/json"
    )
