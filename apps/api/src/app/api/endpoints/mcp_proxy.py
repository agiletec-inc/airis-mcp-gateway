"""
MCP Proxy Endpoint with OpenMCP Lazy Loading Pattern

Claude Code → FastAPI (/mcp/sse) → Docker MCP Gateway (http://mcp-gateway:9390/sse)
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from typing import Any, Dict, Optional
import httpx
import json
import asyncio
from ...core.schema_partitioning import schema_partitioner
from ...core.config import settings
from ...core.protocol_logger import protocol_logger
from ...core.process_manager import get_process_manager
from ...core.dynamic_mcp import get_dynamic_mcp

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

# SSE stream timeout - long read timeout for long-lived connections
SSE_TIMEOUT = httpx.Timeout(
    connect=10.0,      # 10s to establish connection
    read=120.0,        # 120s between chunks (SSE keepalive should be faster)
    write=10.0,        # 10s to send data
    pool=10.0          # 10s to acquire connection
)

# Streaming gateway timeout - similar to SSE
STREAM_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=120.0,
    write=10.0,
    pool=10.0
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

# Session-based response queues for ProcessManager responses
# MCP SSE Transport: responses must be sent via SSE stream, not HTTP response body
_session_response_queues: dict[str, asyncio.Queue] = {}


def get_response_queue(session_id: str) -> asyncio.Queue:
    """Get or create a response queue for a session."""
    if session_id not in _session_response_queues:
        _session_response_queues[session_id] = asyncio.Queue()
    return _session_response_queues[session_id]


def remove_response_queue(session_id: str):
    """Remove a response queue when session ends."""
    _session_response_queues.pop(session_id, None)


class DescriptionMode:
    """Description verbosity modes for tools/list responses."""
    FULL = "full"      # Original description (no truncation)
    SUMMARY = "summary"  # First sentence, max 160 chars (default)
    BRIEF = "brief"    # Very short, max 60 chars
    NONE = "none"      # No description (minimal tokens)


def _summarize_description(
    description: str,
    mode: str = DescriptionMode.SUMMARY,
    max_length: int | None = None
) -> str:
    """
    Generate a compact summary for tools/list responses.

    Args:
        description: Original description text
        mode: One of "full", "summary", "brief", "none"
        max_length: Override max length (optional)

    Returns:
        Processed description or empty string
    """
    if not description:
        return ""

    if mode == DescriptionMode.NONE:
        return ""

    text = description.strip()
    if not text:
        return ""

    if mode == DescriptionMode.FULL:
        return text

    # Determine max length based on mode
    if max_length is None:
        max_length = 160 if mode == DescriptionMode.SUMMARY else 60

    # Extract first sentence
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


def _extract_server_name_from_tool(tool_name: str) -> Optional[str]:
    """
    ツール名からMCPサーバー名を推測して抽出

    Rules:
    1. expandSchema → None (特殊ツール、常に有効)
    2. mindbase_*, github_*, tavily_* → prefix部分がサーバー名
    3. read_file, write_file, list_dir → filesystem or serena (曖昧)
    4. find_symbol, find_referencing_symbols → serena
    5. get_time, fetch_url → built-in (always enabled)

    Args:
        tool_name: ツール名

    Returns:
        サーバー名 or None (判定不能/常時有効)
    """
    if not tool_name:
        return None

    # expandSchemaは特殊ツール（Proxy側で生成）
    if tool_name == "expandSchema":
        return None

    # Built-in servers (Gateway起動時に--serversで自動有効化、DBに記録されない)
    builtin_tools = {
        "get_time", "get_current_time",
        "fetch", "fetch_url",
        "git_status", "git_diff", "git_commit", "git_push",
        "read_memory", "write_memory", "delete_memory"
    }
    if tool_name in builtin_tools:
        return None  # Built-inは常時有効

    # アンダースコア区切りでprefix抽出
    parts = tool_name.split("_")
    if len(parts) >= 2:
        prefix = parts[0]

        # 既知のサーバー名パターン
        known_servers = {
            "mindbase", "github", "tavily", "stripe", "twilio",
            "supabase", "notion", "slack", "figma", "cloudflare",
            "docker", "postgres", "mongodb", "sqlite"
        }

        if prefix in known_servers:
            return prefix

    # filesystem vs serena の曖昧なツール
    # → とりあえずfilesystemとして扱う（serenaのツールはfind_symbolなど特徴的）
    filesystem_tools = {
        "read_file", "write_file", "create_file", "delete_file",
        "list_dir", "list_directory", "search_files",
        "read_text_file", "read_media_file", "read_multiple_files", "edit_file"
    }
    if tool_name in filesystem_tools:
        return "filesystem"

    # serena特有のツール
    serena_tools = {
        "find_symbol", "find_referencing_symbols", "get_symbols_overview",
        "insert_after_symbol", "replace_symbol", "delete_symbol",
        "activate_project", "switch_modes"
    }
    if tool_name in serena_tools:
        return "serena"

    # context7ツール
    if tool_name.startswith("context7_") or tool_name in ["search_docs", "get_documentation"]:
        return "context7"

    # sequential-thinkingツール
    if tool_name in ["think", "sequential_think", "reasoning"]:
        return "sequential-thinking"

    # gateway-controlツール
    if tool_name in ["list_mcp_servers", "enable_mcp_server", "disable_mcp_server", "get_mcp_server_status"]:
        return "airis-mcp-gateway-control"

    # playwright/puppeteerツール
    if any(keyword in tool_name for keyword in ["browser", "page", "click", "navigate", "screenshot"]):
        # より詳細な判定が必要だが、とりあえずplaywrightとする
        return "playwright"

    # 判定不能 → サーバー名として最初の部分を使用
    return parts[0] if parts else None


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
    initialize_request_id = None  # initialize リクエストIDを追跡
    session_id = request.query_params.get("sessionid")  # セッションID追跡
    endpoint_url = None  # エンドポイントURL追跡
    captured_session_id = None  # Gateway から取得したセッションID

    # Codex streamable_http sometimes POSTs to /sse with Content-Length headers.
    # Strip entity headers so the proxied GET doesn't advertise a body it never sends.
    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"content-length", "content-type", "host"}
    }

    if not session_id:
        print("[MCP Proxy] SSE request missing sessionid", dict(request.headers))

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

            async def read_response_queue():
                """ProcessManager のレスポンスキューから読み取る"""
                nonlocal captured_session_id
                while True:
                    if captured_session_id:
                        queue = get_response_queue(captured_session_id)
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
                    await asyncio.sleep(30.0)  # Send keepalive every 30 seconds
                    yield ("keepalive", None)

            # Merge all streams: gateway, response queue, and keepalive
            gateway_gen = read_gateway_stream()
            queue_gen = read_response_queue()
            keepalive_gen = keepalive_sender()

            gateway_task = None
            queue_task = None
            keepalive_task = None

            try:
                while True:
                    # Start tasks if needed
                    if gateway_task is None:
                        gateway_task = asyncio.create_task(gateway_gen.__anext__())
                    if queue_task is None:
                        queue_task = asyncio.create_task(queue_gen.__anext__())
                    if keepalive_task is None:
                        keepalive_task = asyncio.create_task(keepalive_gen.__anext__())

                    # Wait for any to complete
                    done, _ = await asyncio.wait(
                        [gateway_task, queue_task, keepalive_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    for task in done:
                        try:
                            source, data = task.result()
                        except StopAsyncIteration:
                            # Gateway stream ended
                            if captured_session_id:
                                remove_response_queue(captured_session_id)
                            return
                        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError) as e:
                            # Client disconnected - this is normal, exit gracefully
                            print(f"[MCP Proxy] Client disconnected: {type(e).__name__}")
                            if captured_session_id:
                                remove_response_queue(captured_session_id)
                            return
                        except httpx.ReadTimeout:
                            # SSE read timeout - connection may be stale
                            print(f"[MCP Proxy] SSE read timeout (session={captured_session_id})")
                            if captured_session_id:
                                remove_response_queue(captured_session_id)
                            return
                        except httpx.TimeoutException as e:
                            # Other timeout (connect, pool, etc.)
                            print(f"[MCP Proxy] Timeout exception: {type(e).__name__}")
                            if captured_session_id:
                                remove_response_queue(captured_session_id)
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
                            # ProcessManager からのレスポンスを SSE で送信
                            queue_task = None
                            print(f"[MCP Proxy] Sending ProcessManager response via SSE: id={data.get('id')}")
                            yield f"data: {json.dumps(data)}\n\n"
                            continue

                        # Gateway からのメッセージ
                        gateway_task = None
                        line = data

                        if not line:
                            yield "\n"
                            continue

                        # SSE形式: "event: xxx\n" or "data: {...}\n\n"
                        if line.startswith("event: endpoint"):
                            yield f"{line}\n"
                            continue

                        if line.startswith("data: "):
                            data_str = line[6:]  # "data: " を除去

                            # Check if it's an endpoint URL (not JSON)
                            if not data_str.startswith("{") and not data_str.startswith("["):
                                # Extract sessionid from endpoint URL if present
                                if "sessionid=" in data_str:
                                    import re
                                    match = re.search(r'sessionid=([A-Z0-9]+)', data_str)
                                    if match:
                                        captured_session_id = match.group(1)
                                        endpoint_url = data_str.strip()
                                        print(f"[MCP Proxy] Captured endpoint URL with sessionid={captured_session_id}")
                                        # Create response queue for this session
                                        get_response_queue(captured_session_id)
                                yield f"{line}\n"
                                continue

                            try:
                                json_data = json.loads(data_str)

                                # initialize リクエストを検出（SSEストリームで見えることはないが念のため）
                                if isinstance(json_data, dict) and json_data.get("method") == "initialize":
                                    initialize_request_id = json_data.get("id")
                                    print(f"[MCP Proxy] Detected initialize request (id={initialize_request_id})")
                                    await protocol_logger.log_message("client→server", json_data, {"phase": "initialize"})

                                # tools/list レスポンスをインターセプト
                                if isinstance(json_data, dict) and "result" in json_data and "tools" in json_data.get("result", {}):
                                    await protocol_logger.log_message("client→server", json_data, {"phase": "tools_list"})
                                    json_data = await apply_schema_partitioning(json_data)
                                    await protocol_logger.log_message("server→client", json_data, {"phase": "tools_list"})

                                # prompts/list レスポンスをインターセプト（Process MCP サーバーのプロンプトを追加）
                                if isinstance(json_data, dict) and "result" in json_data and "prompts" in json_data.get("result", {}):
                                    json_data = await apply_prompts_merging(json_data)

                                # 変換後のデータを返す
                                yield f"data: {json.dumps(json_data)}\n\n"

                                # initialize responseを検出したらGatewayに notifications/initialized を POST
                                if (isinstance(json_data, dict) and
                                    "result" in json_data and
                                    isinstance(json_data.get("result"), dict) and
                                    "protocolVersion" in json_data.get("result", {})):

                                    print(f"[MCP Proxy] Detected initialize response, sending initialized notification to Gateway")
                                    await protocol_logger.log_message("server→client", json_data, {"phase": "initialize"})

                                    # Gateway に notifications/initialized を POST
                                    initialized_notification = {
                                        "jsonrpc": "2.0",
                                        "method": "notifications/initialized"
                                    }

                                    # sessionid を使って Gateway に POST
                                    if captured_session_id:
                                        gateway_post_url = f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse?sessionid={captured_session_id}"
                                        try:
                                            post_response = await client.post(
                                                gateway_post_url,
                                                json=initialized_notification,
                                                headers={"Content-Type": "application/json"}
                                            )
                                            print(f"[MCP Proxy] Sent initialized notification to Gateway: {post_response.status_code}")
                                        except Exception as e:
                                            print(f"[MCP Proxy] Failed to send initialized notification: {e}")
                                    else:
                                        print("[MCP Proxy] No sessionid available, cannot send initialized notification")

                            except json.JSONDecodeError:
                                # JSONでない場合はそのまま
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
                    remove_response_queue(captured_session_id)
                print(f"[MCP Proxy] SSE stream cleanup complete (session={captured_session_id})")


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

    # Process MCP サーバーからプロンプトを取得して統合
    try:
        process_manager = get_process_manager()
        process_prompts = await process_manager.list_prompts(mode="hot")
        if process_prompts:
            print(f"[Prompts Integration] Merging {len(process_prompts)} HOT prompts with {len(prompts)} docker prompts")
            prompts.extend(process_prompts)
    except Exception as e:
        print(f"[Prompts Integration] Failed to get process prompts: {e}")

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

        print(f"[Dynamic MCP] Background cache refresh complete: {len(dynamic_mcp._tools)} tools")
    except Exception as e:
        print(f"[Dynamic MCP] Background cache refresh failed: {e}")


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

    # Dynamic MCP mode: return only meta-tools (FAST PATH)
    if settings.DYNAMIC_MCP:
        print("[Dynamic MCP] Mode enabled - returning meta-tools only")

        # Return meta-tools IMMEDIATELY (no blocking operations)
        dynamic_mcp = get_dynamic_mcp()
        meta_tools = dynamic_mcp.get_meta_tools()
        data["result"]["tools"] = meta_tools
        print(f"[Dynamic MCP] Returning {len(meta_tools)} meta-tools immediately")

        # Schedule background cache refresh (non-blocking)
        import asyncio
        asyncio.create_task(_refresh_dynamic_mcp_cache(process_manager, docker_tools))

        return data

    # Standard mode: merge HOT tools and apply schema partitioning
    tools = docker_tools

    # Process MCP サーバーからツールを取得して統合（HOT のみ）
    try:
        # HOT サーバーのツールのみ返却（COLD はオンデマンド）
        process_tools = await process_manager.list_tools(mode="hot")
        hot_servers = process_manager.get_hot_servers()
        cold_servers = process_manager.get_cold_servers()
        if process_tools:
            print(f"[SSE Integration] Merging {len(process_tools)} HOT tools with {len(tools)} docker tools")
            print(f"[SSE Integration] HOT servers: {hot_servers}, COLD servers (not included): {cold_servers}")
            tools.extend(process_tools)
    except Exception as e:
        print(f"[SSE Integration] Failed to get process tools: {e}")

    partitioned_tools = []

    for tool in tools:
        tool_name = tool.get("name", "")
        input_schema = tool.get("inputSchema", {})

        # フルスキーマを保存（expandSchema用）
        if input_schema:
            schema_partitioner.store_full_schema(tool_name, input_schema)

        full_description = tool.get("description")
        schema_partitioner.store_tool_description(tool_name, full_description)
        # Use configured description mode (default: brief for token optimization)
        lightweight_description = _summarize_description(
            full_description or "",
            mode=settings.DESCRIPTION_MODE
        )

        # スキーマを分割
        partitioned_schema = schema_partitioner.partition_schema(input_schema)

        # トークン削減効果をログ出力
        reduction = schema_partitioner.get_token_reduction_estimate(input_schema)
        print(f"[Schema Partitioning] {tool_name}: {reduction['full']} → {reduction['partitioned']} tokens ({reduction['reduction']}% reduction)")

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

    # expandSchema ツールを追加
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

    client = httpx.AsyncClient(timeout=STREAM_TIMEOUT)
    try:
        upstream_request = client.build_request(
            method,
            target_url,
            headers=_filter_stream_headers(dict(request.headers)),
            content=payload,
        )
        upstream = await client.send(upstream_request, stream=True, follow_redirects=True)
    except Exception:
        await client.aclose()
        raise

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

    return StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


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

    print(f"[MCP Proxy] JSON-RPC request: method={method}, sessionid={session_id}")

    # セッション状態を追跡（初期化済みかどうか）
    if not hasattr(_proxy_jsonrpc_request, '_initialized_sessions'):
        _proxy_jsonrpc_request._initialized_sessions = set()

    # Auto-initialize session if tools/call arrives for uninitialized session
    # This is a fallback for clients that don't follow proper MCP init sequence
    if method == "tools/call" and session_id and session_id not in _proxy_jsonrpc_request._initialized_sessions:
        print(f"[MCP Proxy] Session {session_id} not initialized, running init sequence")
        gateway_post_url = f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse?sessionid={session_id}"

        async with httpx.AsyncClient(timeout=30.0) as init_client:
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
                    print(f"[MCP Proxy] Initialize request failed: {init_response.status_code}")
                    # Continue anyway - let the actual request fail with proper error
                else:
                    print(f"[MCP Proxy] Initialize request accepted: {init_response.status_code}")

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
                        _proxy_jsonrpc_request._initialized_sessions.add(session_id)
                        print(f"[MCP Proxy] Session {session_id} initialized successfully")
                    else:
                        print(f"[MCP Proxy] Initialized notification failed: {notif_response.status_code}")

            except httpx.TimeoutException:
                print(f"[MCP Proxy] Init sequence timed out for session {session_id}")
            except Exception as e:
                print(f"[MCP Proxy] Init sequence failed: {e}")

    # expandSchema ツールコール処理
    if rpc_request.get("method") == "tools/call":
        params = rpc_request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "expandSchema":
            # expandSchema は Gateway にproxyしない（ローカル処理）
            return await handle_expand_schema(rpc_request)

        # Dynamic MCP meta-tools (only when DYNAMIC_MCP=true)
        if tool_name == "airis-find":
            return await handle_airis_find(rpc_request, session_id=session_id)

        if tool_name == "airis-exec":
            return await handle_airis_exec(rpc_request, session_id=session_id)

        if tool_name == "airis-schema":
            return await handle_airis_schema(rpc_request, session_id=session_id)

    # prompts/get リクエスト処理
    if rpc_request.get("method") == "prompts/get":
        params = rpc_request.get("params", {})
        prompt_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # Process MCP サーバーのプロンプトを優先的に処理
        # (キャッシュがなくても get_prompt は有効なサーバーを検索する)
        try:
            process_manager = get_process_manager()
            print(f"[MCP Proxy] Trying ProcessManager for prompt: {prompt_name}")
            server_response = await process_manager.get_prompt(prompt_name, arguments)

            # Prompt not found の場合は Docker Gateway にフォールバック
            if "error" in server_response and server_response["error"].get("code") == -32601:
                print(f"[MCP Proxy] Prompt {prompt_name} not found in ProcessManager, falling through to Gateway")
            else:
                # JSON-RPC レスポンス形式で返す (クライアントのIDを使用)
                response_data = {
                    "jsonrpc": "2.0",
                    "id": rpc_request.get("id"),
                }
                # サーバーレスポンスからresultまたはerrorを抽出
                if "error" in server_response:
                    response_data["error"] = server_response["error"]
                else:
                    response_data["result"] = server_response.get("result")

                # MCP SSE Transport: レスポンスはSSEストリーム経由で送信
                if session_id:
                    queue = get_response_queue(session_id)
                    await queue.put(response_data)
                    print(f"[MCP Proxy] Queued prompts/get response for session {session_id}")
                    return Response(status_code=202)

                # sessionid がない場合はHTTPレスポンスで返す（フォールバック）
                return Response(
                    content=json.dumps(response_data),
                    status_code=200,
                    media_type="application/json"
                )
        except Exception as e:
            print(f"[MCP Proxy] ProcessManager prompt routing failed: {e}")

    # tools/call リクエスト処理
    if rpc_request.get("method") == "tools/call":
        params = rpc_request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        # Process MCP サーバーのツールかチェック
        try:
            process_manager = get_process_manager()
            # ツール名がProcessManagerに登録されているか確認
            if tool_name in process_manager._tool_to_server:
                print(f"[MCP Proxy] Routing {tool_name} to ProcessManager")
                server_response = await process_manager.call_tool(tool_name, arguments)
                # JSON-RPC レスポンス形式で返す (クライアントのIDを使用)
                response_data = {
                    "jsonrpc": "2.0",
                    "id": rpc_request.get("id"),
                }
                # サーバーレスポンスからresultまたはerrorを抽出
                if "error" in server_response:
                    response_data["error"] = server_response["error"]
                else:
                    response_data["result"] = server_response.get("result")

                # MCP SSE Transport: レスポンスはSSEストリーム経由で送信
                if session_id:
                    queue = get_response_queue(session_id)
                    await queue.put(response_data)
                    print(f"[MCP Proxy] Queued tools/call response for session {session_id}")
                    return Response(status_code=202)

                # sessionid がない場合はHTTPレスポンスで返す（フォールバック）
                return Response(
                    content=json.dumps(response_data),
                    status_code=200,
                    media_type="application/json"
                )
        except Exception as e:
            print(f"[MCP Proxy] ProcessManager routing check failed: {e}")

    # その他のツールコールはGatewayにproxy
    if not session_id:
        # RMCP streamable_http clients (Codex) expect streaming responses.
        return await _proxy_streaming_gateway_request(
            request,
            initialize_request_id=rpc_request.get("id") if is_initialize_request else None,
        )

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

        # initialize リクエストが成功したら、notifications/initialized を Gateway に送信
        if is_initialize_request and response.status_code in (200, 202):
            print(f"[MCP Proxy] Initialize request successful, sending initialized notification to Gateway (sessionid={session_id})")
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
                print(f"[MCP Proxy] Sent initialized notification: {init_response.status_code}")
            except Exception as e:
                print(f"[MCP Proxy] Failed to send initialized notification: {e}")

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

    from ...core.dynamic_mcp import ToolInfo, ServerInfo

    # Always ensure servers are cached (even if tools already exist)
    # This is needed because tools/list populates tools but not necessarily servers
    if not dynamic_mcp._servers:
        print("[Dynamic MCP] Server cache empty, refreshing...")
        # Cache server info for ALL enabled process servers (including COLD)
        for name in process_manager.get_enabled_servers():
            status = process_manager.get_server_status(name)
            dynamic_mcp._servers[name] = ServerInfo(
                name=name,
                enabled=status.get("enabled", False),
                mode=status.get("mode", "cold"),
                tools_count=status.get("tools_count", 0),
                source="process"
            )

        print(f"[Dynamic MCP] Cached {len(dynamic_mcp._servers)} servers")

    # Auto-refresh ProcessManager tools if not yet cached
    # (Docker Gateway tools may be pre-cached at startup, but we still need ProcessManager tools)
    # Only load HOT servers here - COLD servers are loaded on-demand by smart discovery
    has_process_tools = any(t.source == "process" for t in dynamic_mcp._tools.values())
    if not has_process_tools:
        print("[Dynamic MCP] No ProcessManager tools in cache, refreshing from HOT servers...")
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
        print(f"[Dynamic MCP] Cached {len(all_tools)} process tools (total: {len(dynamic_mcp._tools)})")

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
            print(f"[Dynamic MCP] Added server '{server}' to cache (mode={server_info.mode})")

        # If it's a COLD server with no tools cached, start it and cache tools
        # Note: tools_count is metadata, we need to check if tools are actually in _tools dict
        server_has_tools = any(t.server == server for t in dynamic_mcp._tools.values())
        if is_process and server_info and server_info.mode == "cold" and not server_has_tools:
            print(f"[Dynamic MCP] Starting COLD server '{server}' to get tools...")
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
            print(f"[Dynamic MCP] Loaded {len(server_tools)} tools from '{server}'")

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

    if results['tools']:
        lines.append("## Tools")
        for t in results['tools']:
            lines.append(f"- **{t['server']}:{t['name']}** - {t['description']}")

    if not results['tools'] and not results['servers']:
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
        queue = get_response_queue(session_id)
        await queue.put(response_data)
        print(f"[Dynamic MCP] Queued airis-find response for session {session_id}")
        return Response(status_code=202)

    # Fallback to HTTP response if no session_id
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

    print(f"[Dynamic MCP] airis-exec: {tool_ref} -> server={server_name}, tool={tool_name}")

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

    # Route to ProcessManager (only if server is registered AND enabled)
    # If server exists but is disabled in ProcessManager, fall through to Docker Gateway
    process_manager = get_process_manager()
    enabled_servers = process_manager.get_enabled_servers()
    if process_manager.is_process_server(server_name) and server_name in enabled_servers:
        result = await process_manager.call_tool_on_server(server_name, tool_name, tool_args)

        response_data = {
            "jsonrpc": "2.0",
            "id": rpc_request.get("id"),
        }
        if "error" in result:
            response_data["error"] = result["error"]
        else:
            response_data["result"] = result.get("result")

        # Send via SSE queue if session exists
        if session_id:
            queue = get_response_queue(session_id)
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
    print(f"[Dynamic MCP] Proxying airis-exec to Docker Gateway: {tool_name}")

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
            queue = get_response_queue(session_id)
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
            queue = get_response_queue(session_id)
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
        queue = get_response_queue(session_id)
        await queue.put(response_data)
        print(f"[Dynamic MCP] Queued airis-schema response for session {session_id}")
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
        # フルスキーマから該当パスを取得
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
