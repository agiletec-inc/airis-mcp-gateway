"""
AIRIS MCP Gateway API - Hybrid MCP Multiplexer.

Routes:
- Docker MCP servers -> Docker MCP Gateway (port 9390)
- Process MCP servers (uvx/npx) -> Direct subprocess management
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os

from .api.endpoints import mcp_proxy
from .api.endpoints import process_mcp
from .api.endpoints import sse_tools
from .core.process_manager import initialize_process_manager, get_process_manager
from .core.process_runner import ProcessState
from .core.logging import setup_logging, get_logger
from .middleware.auth import OptionalBearerAuth
from .middleware.request_id import RequestIDMiddleware
from .middleware.logging_context import LoggingContextMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.http_metrics import HTTPMetricsMiddleware, get_http_metrics_store
from .middleware.request_size import RequestSizeLimitMiddleware

# Initialize logging
setup_logging()
logger = get_logger(__name__)

MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://gateway:9390")
MCP_CONFIG_PATH = os.getenv("MCP_CONFIG_PATH", "/app/mcp-config.json")
SHUTDOWN_TIMEOUT = int(os.getenv("SHUTDOWN_TIMEOUT", "30"))  # seconds

# Retain strong references to background tasks so the GC does not collect
# them mid-execution (see https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task).
_background_tasks: set[asyncio.Task] = set()


def _spawn_background_task(
    coro,
    *,
    name: str | None = None,
    on_error=None,
) -> asyncio.Task:
    """Create a background task that survives until it finishes on its own."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    if on_error is not None:
        task.add_done_callback(on_error)
    return task


async def _wait_for_docker_gateway(timeout: float = 30.0) -> bool:
    """Poll the Docker Gateway /health endpoint until it responds 200.

    Uses exponential backoff so warm restarts recover quickly (~100ms) and
    cold starts do not flood the gateway with requests.

    Returns True on success, False on timeout.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    delay = 0.1
    gateway_url = MCP_GATEWAY_URL.rstrip("/")

    async with httpx.AsyncClient(timeout=1.0) as client:
        while loop.time() < deadline:
            try:
                resp = await client.get(f"{gateway_url}/health")
                if resp.status_code == 200:
                    return True
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPError):
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 1.0)

    return False


async def _precache_docker_gateway_tools():
    """
    Background task to pre-cache Docker Gateway tools at startup.

    MCP SSE Protocol requires keeping the GET stream open while POSTing.
    This function uses a concurrent approach:
    1. Open GET /sse stream (kept open for responses)
    2. Parse endpoint event to get session URL
    3. POST initialize, initialized, tools/list
    4. Continue reading GET stream for tools/list response
    """
    import json

    # Wait for the Gateway to accept /health instead of sleeping blindly.
    if not await _wait_for_docker_gateway(timeout=30.0):
        logger.warning("[Startup] Docker Gateway did not become ready in 30s; skipping precache")
        return

    gateway_url = MCP_GATEWAY_URL.rstrip("/")
    logger.info(f"[Startup] Pre-caching Docker Gateway tools...")

    docker_tools = []
    endpoint_url = None
    event_type = None

    # Signaled by the outer SSE read loop below when the Gateway's initialize
    # response (id=1) arrives, so send_requests() can wait for that real
    # event instead of a fixed sleep (issue #194).
    init_response_event = asyncio.Event()

    async def send_requests(client, endpoint):
        """Send MCP protocol requests."""
        # No sleep needed here: `endpoint` is only known once the outer loop
        # has already received the Gateway's "endpoint" SSE event, which by
        # construction means the stream is established.

        # Initialize
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "airis-startup", "version": "1.0.0"}
            }
        }
        await client.post(
            endpoint,
            json=init_request,
            headers={"Content-Type": "application/json"}
        )

        # Wait for the actual initialize response (id=1) on the GET stream,
        # instead of a fixed sleep that raced under load (issue #194).
        try:
            await asyncio.wait_for(init_response_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(
                "[Startup] Timed out waiting for initialize response; "
                "sending initialized notification anyway"
            )

        # Initialized notification
        await client.post(
            endpoint,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={"Content-Type": "application/json"}
        )
        # notifications/initialized has no JSON-RPC response by protocol
        # design, so there is no-observable-event to await here: the Docker
        # MCP Gateway processes it asynchronously after the HTTP POST
        # completes (documented upstream limitation, see
        # .github/ISSUE_TEMPLATE/mcp-init-race.md). Bounded last-resort wait
        # kept per issue #194.
        await asyncio.sleep(0.2)

        # tools/list
        await client.post(
            endpoint,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={"Content-Type": "application/json"}
        )
        logger.info(f"[Startup] Sent all requests to {endpoint}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Open SSE stream and keep it open while processing
            async with client.stream(
                "GET",
                f"{gateway_url}/sse",
                headers={"Accept": "text/event-stream"},
                timeout=15.0
            ) as response:
                sender_task = None
                async for line in response.aiter_lines():
                    line = line.strip()

                    # Parse event type
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                        continue

                    # Parse data
                    if line.startswith("data:"):
                        data_str = line[5:].strip()

                        # Endpoint event - start sending requests
                        if event_type == "endpoint":
                            endpoint_url = f"{gateway_url}{data_str}"
                            logger.info(f"[Startup] Got endpoint: {endpoint_url}")
                            # Start sending requests in background
                            sender_task = asyncio.create_task(send_requests(client, endpoint_url))
                            continue

                        # JSON response - look for tools/list
                        if data_str.startswith("{"):
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError as e:
                                # Surface the failure so stuck precache is diagnosable.
                                logger.warning(
                                    "[Startup] Discarding non-JSON SSE data from Gateway: %s (raw=%s)",
                                    e,
                                    data_str[:200],
                                )
                                continue

                            if data.get("id") == 1 and ("result" in data or "error" in data):
                                init_response_event.set()
                                continue

                            if data.get("id") == 2 and "result" in data:
                                docker_tools = data["result"].get("tools", [])
                                logger.info(f"[Startup] Received {len(docker_tools)} tools from Gateway")
                                break

                # Cancel sender if still running
                if sender_task and not sender_task.done():
                    sender_task.cancel()

            if docker_tools:
                # Cache Docker tools in DynamicMCP
                from .core.dynamic_mcp import get_dynamic_mcp, ToolInfo, ServerInfo
                dynamic_mcp = get_dynamic_mcp()

                docker_server_tools = {}
                for tool in docker_tools:
                    tool_name = tool.get("name", "")
                    if tool_name and tool_name not in dynamic_mcp._tools:
                        server_name = dynamic_mcp._infer_server_name(tool_name)
                        dynamic_mcp._tools[tool_name] = ToolInfo(
                            name=tool_name,
                            server=server_name,
                            description=tool.get("description", ""),
                            input_schema=tool.get("inputSchema", {}),
                            source="docker"
                        )
                        dynamic_mcp._tool_to_server[tool_name] = server_name
                        docker_server_tools[server_name] = docker_server_tools.get(server_name, 0) + 1

                for server_name, tools_count in docker_server_tools.items():
                    if server_name not in dynamic_mcp._servers:
                        dynamic_mcp._servers[server_name] = ServerInfo(
                            name=server_name,
                            enabled=True,
                            mode="docker",
                            tools_count=tools_count,
                            source="docker"
                        )

                logger.info(f"[Startup] Pre-cached {len(docker_tools)} Docker Gateway tools from {len(docker_server_tools)} servers")
            else:
                logger.info("[Startup] No Docker Gateway tools found in response")

    except Exception as e:
        import traceback
        logger.info(f"[Startup] Docker Gateway pre-cache failed: {e}")
        logger.info(f"[Startup] Traceback: {traceback.format_exc()}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AIRIS MCP Gateway API starting")
    logger.info(f"Docker Gateway URL: {MCP_GATEWAY_URL}")
    logger.info(f"MCP Config Path: {MCP_CONFIG_PATH}")

    # Validate and log configuration warnings
    from .core.config import log_startup_warnings
    log_startup_warnings()

    # Initialize ProcessManager for uvx/npx servers
    try:
        await initialize_process_manager(MCP_CONFIG_PATH)
        manager = get_process_manager()
        logger.info(f"Process servers: {manager.get_server_names()}")
        logger.info(f"Enabled: {manager.get_enabled_servers()}")

        # Subscribe the SSE fan-out so clients are notified whenever a
        # server enters or leaves the HOT set (enable / disable / idle-kill).
        from .api.endpoints.tools_list_notifier import install_tools_list_changed_fanout
        install_tools_list_changed_fanout()

        # Pre-warm HOT servers to avoid cold start timeouts on first tools/list
        # This runs in parallel and ensures servers are ready before clients connect
        hot_servers = manager.get_hot_servers()
        if hot_servers:
            logger.info(f"Pre-warming HOT servers: {hot_servers}")
            prewarm_status = await manager.prewarm_hot_servers()
            ready = sum(1 for v in prewarm_status.values() if v)
            logger.info(f"Pre-warm complete: {ready}/{len(hot_servers)} servers ready")

        # Start background task to pre-cache Docker Gateway tools
        def _handle_precache_error(task: asyncio.Task):
            """Log any unhandled errors from the precache task."""
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.info(f"[Startup] Docker Gateway pre-cache task failed: {e}")

        _spawn_background_task(
            _precache_docker_gateway_tools(),
            name="precache_docker_gateway_tools",
            on_error=_handle_precache_error,
        )

    except Exception as e:
        logger.error(f"ProcessManager init failed: {e}")

    # Start periodic cleanup of stale session queues and stream bridges.
    async def _periodic_queue_cleanup():
        while True:
            await asyncio.sleep(600)  # every 10 minutes
            try:
                removed_queues = await mcp_proxy.cleanup_stale_queues()
                if removed_queues > 0:
                    logger.info(f"Cleaned up {removed_queues} stale session queue(s)")
            except Exception as e:
                logger.warning(f"Session queue cleanup error: {e}")

            try:
                removed_bridges = await mcp_proxy.cleanup_stale_stream_bridges()
                if removed_bridges > 0:
                    logger.info(f"Cleaned up {removed_bridges} stale stream bridge(s)")
            except Exception as e:
                logger.warning(f"Stream bridge cleanup error: {e}")

    cleanup_task = _spawn_background_task(
        _periodic_queue_cleanup(),
        name="periodic_queue_cleanup",
    )

    # Start periodic cleanup of expired rate-limit entries so the in-memory
    # store does not grow unbounded on long-running instances.
    async def _periodic_rate_limit_cleanup():
        from .middleware.rate_limit import get_rate_limit_store

        store = get_rate_limit_store()
        while True:
            await asyncio.sleep(300)  # every 5 minutes
            try:
                removed = store.cleanup_expired()
                if removed > 0:
                    logger.info(f"Cleaned up {removed} expired rate-limit entries")
            except Exception as e:
                logger.warning(f"Rate limit cleanup error: {e}")

    rate_limit_cleanup_task = _spawn_background_task(
        _periodic_rate_limit_cleanup(),
        name="periodic_rate_limit_cleanup",
    )

    yield

    cleanup_task.cancel()
    rate_limit_cleanup_task.cancel()

    # Graceful shutdown with timeout
    logger.info(f"Shutting down (timeout: {SHUTDOWN_TIMEOUT}s)...")
    try:
        manager = get_process_manager()

        # Shutdown with timeout
        try:
            await asyncio.wait_for(
                manager.shutdown(),
                timeout=SHUTDOWN_TIMEOUT
            )
            logger.info("Graceful shutdown completed")
        except asyncio.TimeoutError:
            logger.warning(
                f"Shutdown timed out after {SHUTDOWN_TIMEOUT}s, "
                "some processes may have been force-killed"
            )
    except Exception as e:
        logger.error(f"ProcessManager shutdown error: {e}")


app = FastAPI(
    title="AIRIS MCP Gateway API",
    description="Proxy to docker/mcp-gateway with initialized notification fix",
    lifespan=lifespan,
)


def _parse_allowed_origins() -> list[str]:
    """
    Parse ALLOWED_ORIGINS environment variable.

    Format: comma-separated list of origins (scheme+host+port)
    Example: ALLOWED_ORIGINS=http://localhost:3000,https://app.example.com

    Returns ["*"] if not set (development mode).
    """
    raw = os.getenv("ALLOWED_ORIGINS", "")
    if not raw:
        return ["*"]

    # Split, strip whitespace, filter empty strings
    # CRITICAL: "a, b".split(",") -> ["a", " b"] - must strip!
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]

    if not origins:
        return ["*"]

    return origins


ALLOWED_ORIGINS = _parse_allowed_origins()
if ALLOWED_ORIGINS == ["*"]:
    logger.warning("CORS: wildcard origin enabled (development mode). Set ALLOWED_ORIGINS for production.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Optional API key auth - only active if AIRIS_API_KEY env var is set
# Skips auth for /health, /ready, /
app.add_middleware(OptionalBearerAuth)

# Middleware order matters! Last added = first executed in request chain.
# Execution order: RequestID -> LoggingContext -> RateLimit -> RequestSize -> HTTPMetrics -> Auth -> CORS -> Handler

# HTTP metrics - records request count and latency (includes 429s, 413s)
app.add_middleware(HTTPMetricsMiddleware)

# Request size limit - reject large payloads early (default 10MB)
app.add_middleware(RequestSizeLimitMiddleware)

# Rate limiting - 429 responses will include request_id in logs
# Skips /health, /ready, /metrics
app.add_middleware(RateLimitMiddleware)

# Logging context - sets request_id in ContextVar for structured logging
app.add_middleware(LoggingContextMiddleware)

# Request ID middleware - MUST be last (executes first in request chain)
# Ensures every request has X-Request-ID for tracing
app.add_middleware(RequestIDMiddleware)

# Mount MCP proxy router (Docker Gateway proxy with initialized notification fix)
app.include_router(mcp_proxy.router, prefix="/mcp", tags=["mcp"])

# Mount Process MCP router (direct uvx/npx process management)
app.include_router(process_mcp.router, prefix="/process", tags=["process-mcp"])

# Mount SSE tools router (real-time tool discovery)
app.include_router(sse_tools.router, prefix="/api", tags=["sse-tools"])


# Root-level SSE endpoint for Claude Code compatibility
@app.get("/sse")
async def root_sse_proxy(request: Request):
    """SSE endpoint at root level for Claude Code compatibility."""
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        mcp_proxy.proxy_sse_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/sse")
async def root_sse_proxy_post(request: Request):
    """
    POST to /sse for MCP SSE transport.

    MCP SSE transport:
    - GET /sse → SSE stream (server-initiated messages)
    - POST /sse?sessionid=X → JSON-RPC request/response

    POST requests with sessionid should ALWAYS go through JSON-RPC handler.
    """
    from fastapi.responses import StreamingResponse

    # POST requests with sessionid are JSON-RPC requests - handle directly
    session_id = request.query_params.get("sessionid")
    if session_id:
        return await mcp_proxy._proxy_jsonrpc_request(request)

    # Legacy: POST without sessionid and requesting SSE stream
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept.lower():
        return StreamingResponse(
            mcp_proxy.proxy_sse_stream(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    # Fall back to JSON-RPC proxy
    return await mcp_proxy._proxy_jsonrpc_request(request)


@app.api_route("/.well-known/{path:path}", methods=["GET", "HEAD"])
async def root_well_known_proxy(request: Request, path: str):
    """Expose streamable HTTP discovery at the application root."""
    return await mcp_proxy.proxy_root_well_known(request, path)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/health/servers")
async def health_servers():
    """
    Per-server health map — surfaces upstream failures that otherwise only
    show up as a log line while the server silently vanishes from
    tools/list / airis-find (issue #197).

    Read-only, no auth change (matches /health, /ready — localhost-only gateway).
    """
    manager = get_process_manager()
    servers = {}
    for name in manager.get_server_names():
        config = manager._server_configs.get(name)
        health_record = manager.get_server_health(name)
        servers[name] = {
            "name": name,
            "mode": config.mode.value if config else None,
            "enabled": config.enabled if config else False,
            "policy_disabled": getattr(config, "policy_disabled", False) if config else False,
            "status": health_record.status,
            "last_error": health_record.last_error,
            "last_checked": health_record.last_checked,
        }
    return {"servers": servers}


@app.get("/ready")
async def ready():
    """
    Readiness check for the MCP Gateway.

    Returns ready=true only when:
    1. Docker Gateway is reachable
    2. All HOT servers are in READY state

    This ensures Claude Code slash commands are available from startup.
    """
    # Check Docker Gateway
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{MCP_GATEWAY_URL}/health")
            gateway_ok = resp.status_code == 200
    except (httpx.RequestError, httpx.HTTPStatusError):
        gateway_ok = False

    # Check HOT servers
    manager = get_process_manager()
    hot_servers = manager.get_hot_servers()
    hot_status = {}
    all_hot_ready = True

    for name in hot_servers:
        runner = manager.get_runner(name)
        if runner:
            is_ready = runner.state == ProcessState.READY
            hot_status[name] = "ready" if is_ready else runner.state.value
            if not is_ready:
                all_hot_ready = False
        else:
            hot_status[name] = "not_found"
            all_hot_ready = False

    # Ready only if gateway is ok AND all HOT servers are ready
    is_ready = gateway_ok and (all_hot_ready or len(hot_servers) == 0)

    return {
        "ready": is_ready,
        "gateway": "ok" if gateway_ok else "unreachable",
        "hot_servers": hot_status,
        "hot_servers_ready": f"{sum(1 for s in hot_status.values() if s == 'ready')}/{len(hot_servers)}",
    }


@app.get("/")
async def root():
    return {
        "service": "airis-mcp-gateway-api",
        "gateway_url": MCP_GATEWAY_URL,
    }


@app.get("/metrics")
async def metrics():
    """
    Prometheus-style metrics endpoint.

    Metrics exposed:
    - mcp_active_processes: Number of running MCP server processes
    - mcp_stopped_processes: Number of stopped MCP server processes
    - mcp_server_enabled: Whether a server is enabled (1) or disabled (0)
    - mcp_server_tools: Number of tools provided by a server
    - mcp_server_uptime_seconds: Uptime of a running server
    - mcp_server_spawn_total: Total number of process spawns (restarts)
    - mcp_server_calls_total: Total number of tool calls
    - mcp_server_latency_p50_ms: 50th percentile latency
    - mcp_server_latency_p95_ms: 95th percentile latency
    - mcp_server_latency_p99_ms: 99th percentile latency
    """
    from fastapi.responses import PlainTextResponse

    manager = get_process_manager()
    process_status = manager.get_all_status(include_metrics=True)

    active = sum(1 for s in process_status if s.get("state") == "ready")
    stopped = sum(1 for s in process_status if s.get("state") == "stopped")
    total = len(process_status)

    lines = [
        "# HELP mcp_active_processes Number of running MCP server processes",
        "# TYPE mcp_active_processes gauge",
        f"mcp_active_processes {active}",
        "",
        "# HELP mcp_stopped_processes Number of stopped MCP server processes",
        "# TYPE mcp_stopped_processes gauge",
        f"mcp_stopped_processes {stopped}",
        "",
        "# HELP mcp_total_processes Total number of configured MCP servers",
        "# TYPE mcp_total_processes gauge",
        f"mcp_total_processes {total}",
        "",
        "# HELP mcp_server_enabled Whether server is enabled (1) or disabled (0)",
        "# TYPE mcp_server_enabled gauge",
    ]

    for status in process_status:
        name = status.get("name", "unknown")
        enabled = 1 if status.get("enabled") else 0
        lines.append(f'mcp_server_enabled{{server="{name}"}} {enabled}')

    lines.extend(["", "# HELP mcp_server_tools Number of tools provided by server", "# TYPE mcp_server_tools gauge"])
    for status in process_status:
        name = status.get("name", "unknown")
        tools = status.get("tools_count", 0)
        lines.append(f'mcp_server_tools{{server="{name}"}} {tools}')

    lines.extend(["", "# HELP mcp_server_uptime_seconds Uptime of running server in seconds", "# TYPE mcp_server_uptime_seconds gauge"])
    for status in process_status:
        name = status.get("name", "unknown")
        metrics_data = status.get("metrics", {})
        uptime_ms = metrics_data.get("uptime_ms")
        if uptime_ms is not None:
            lines.append(f'mcp_server_uptime_seconds{{server="{name}"}} {uptime_ms / 1000:.2f}')

    lines.extend(["", "# HELP mcp_server_spawn_total Total number of process spawns (includes restarts)", "# TYPE mcp_server_spawn_total counter"])
    for status in process_status:
        name = status.get("name", "unknown")
        metrics_data = status.get("metrics", {})
        spawn_count = metrics_data.get("spawn_count", 0)
        lines.append(f'mcp_server_spawn_total{{server="{name}"}} {spawn_count}')

    lines.extend(["", "# HELP mcp_server_calls_total Total number of tool calls", "# TYPE mcp_server_calls_total counter"])
    for status in process_status:
        name = status.get("name", "unknown")
        metrics_data = status.get("metrics", {})
        total_calls = metrics_data.get("total_calls", 0)
        lines.append(f'mcp_server_calls_total{{server="{name}"}} {total_calls}')

    lines.extend(["", "# HELP mcp_server_latency_p50_ms 50th percentile latency in milliseconds", "# TYPE mcp_server_latency_p50_ms gauge"])
    for status in process_status:
        name = status.get("name", "unknown")
        metrics_data = status.get("metrics", {})
        p50 = metrics_data.get("latency_p50_ms")
        if p50 is not None:
            lines.append(f'mcp_server_latency_p50_ms{{server="{name}"}} {p50}')

    lines.extend(["", "# HELP mcp_server_latency_p95_ms 95th percentile latency in milliseconds", "# TYPE mcp_server_latency_p95_ms gauge"])
    for status in process_status:
        name = status.get("name", "unknown")
        metrics_data = status.get("metrics", {})
        p95 = metrics_data.get("latency_p95_ms")
        if p95 is not None:
            lines.append(f'mcp_server_latency_p95_ms{{server="{name}"}} {p95}')

    lines.extend(["", "# HELP mcp_server_latency_p99_ms 99th percentile latency in milliseconds", "# TYPE mcp_server_latency_p99_ms gauge"])
    for status in process_status:
        name = status.get("name", "unknown")
        metrics_data = status.get("metrics", {})
        p99 = metrics_data.get("latency_p99_ms")
        if p99 is not None:
            lines.append(f'mcp_server_latency_p99_ms{{server="{name}"}} {p99}')

    # HTTP request metrics
    http_store = get_http_metrics_store()
    request_counts = http_store.get_request_counts()
    latency_stats = http_store.get_latency_stats()

    lines.extend(["", "# HELP http_requests_total Total HTTP requests", "# TYPE http_requests_total counter"])
    for (method, path, status_code), count in sorted(request_counts.items()):
        lines.append(f'http_requests_total{{method="{method}",path="{path}",status="{status_code}"}} {count}')

    lines.extend(["", "# HELP http_request_latency_p50_ms HTTP request latency 50th percentile", "# TYPE http_request_latency_p50_ms gauge"])
    for path, stats in sorted(latency_stats.items()):
        if stats["p50"] is not None:
            lines.append(f'http_request_latency_p50_ms{{path="{path}"}} {stats["p50"]:.2f}')

    lines.extend(["", "# HELP http_request_latency_p95_ms HTTP request latency 95th percentile", "# TYPE http_request_latency_p95_ms gauge"])
    for path, stats in sorted(latency_stats.items()):
        if stats["p95"] is not None:
            lines.append(f'http_request_latency_p95_ms{{path="{path}"}} {stats["p95"]:.2f}')

    lines.extend(["", "# HELP http_request_latency_p99_ms HTTP request latency 99th percentile", "# TYPE http_request_latency_p99_ms gauge"])
    for path, stats in sorted(latency_stats.items()):
        if stats["p99"] is not None:
            lines.append(f'http_request_latency_p99_ms{{path="{path}"}} {stats["p99"]:.2f}')

    lines.append("")
    return PlainTextResponse("\n".join(lines), media_type="text/plain")
