"""
ProcessRunner - uvx/npx MCP Server Process Management

Handles:
- Lazy process startup on first request
- StdIO JSON-RPC communication
- Automatic idle kill
- Proper initialized notification handling
"""

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from enum import Enum

# For memory/CPU metrics
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class ProcessState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    INITIALIZING = "initializing"
    READY = "ready"
    STOPPING = "stopping"


@dataclass
class ProcessConfig:
    """Configuration for a process-based MCP server."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    idle_timeout: int = 120  # seconds (base, can be overridden by adaptive TTL)
    # Adaptive TTL settings
    adaptive_ttl_enabled: bool = True
    min_ttl: int = 30  # minimum TTL in seconds
    max_ttl: int = 300  # maximum TTL in seconds
    ttl_window: int = 300  # window for measuring call frequency (5 minutes)


class ProcessRunner:
    """
    Manages a single uvx/npx MCP server process.

    Lifecycle:
    1. STOPPED -> start() -> STARTING -> RUNNING
    2. RUNNING -> send initialize -> INITIALIZING
    3. INITIALIZING -> receive initialize response -> send initialized -> READY
    4. READY -> tools/call works
    5. idle_timeout exceeded -> STOPPING -> STOPPED
    """

    def __init__(
        self,
        config: ProcessConfig,
        on_stderr: Optional[Callable[[str, str], None]] = None,
    ):
        self.config = config
        self.on_stderr = on_stderr or self._default_stderr_handler

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._state = ProcessState.STOPPED
        self._last_used = 0.0
        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._reaper_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Server capabilities (populated after initialize)
        self._server_info: dict[str, Any] = {}
        self._tools: list[dict[str, Any]] = []
        self._prompts: list[dict[str, Any]] = []

        # Metrics tracking
        self._started_at: Optional[float] = None
        self._spawn_count = 0
        self._idle_kill_count = 0
        self._last_error: Optional[str] = None
        self._call_latencies: deque[float] = deque(maxlen=100)  # Last 100 calls
        self._total_calls = 0

        # Adaptive TTL tracking
        self._call_timestamps: deque[float] = deque(maxlen=1000)  # Recent call timestamps
        self._current_ttl: float = config.idle_timeout  # Start with base TTL
        self._cold_start_time: Optional[float] = None  # Track cold start duration

    @property
    def state(self) -> ProcessState:
        return self._state

    @property
    def is_ready(self) -> bool:
        return self._state == ProcessState.READY

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self._tools

    @property
    def prompts(self) -> list[dict[str, Any]]:
        return self._prompts

    @property
    def current_ttl(self) -> float:
        """Get current adaptive TTL value."""
        return self._current_ttl

    def _calculate_adaptive_ttl(self) -> float:
        """
        Calculate adaptive TTL based on usage patterns.

        Algorithm:
        1. Count calls within the TTL window
        2. Scale TTL based on call frequency
        3. Consider cold start cost (longer TTL for expensive cold starts)

        Returns:
            Calculated TTL in seconds
        """
        if not self.config.adaptive_ttl_enabled:
            return self.config.idle_timeout

        now = time.time()
        window_start = now - self.config.ttl_window

        # Count recent calls
        recent_calls = sum(1 for ts in self._call_timestamps if ts > window_start)

        # Calculate calls per minute
        calls_per_minute = (recent_calls / self.config.ttl_window) * 60

        # Base scaling: more calls = longer TTL
        # 0 calls/min -> min_ttl
        # 10+ calls/min -> max_ttl
        if calls_per_minute <= 0:
            base_ttl = self.config.min_ttl
        elif calls_per_minute >= 10:
            base_ttl = self.config.max_ttl
        else:
            # Linear interpolation
            ratio = calls_per_minute / 10
            base_ttl = self.config.min_ttl + ratio * (self.config.max_ttl - self.config.min_ttl)

        # Cold start penalty: if cold start was slow, extend TTL
        if self._cold_start_time and self._cold_start_time > 5.0:
            # Add penalty proportional to cold start time
            cold_start_penalty = min(self._cold_start_time * 10, 60)  # max 60s bonus
            base_ttl = min(base_ttl + cold_start_penalty, self.config.max_ttl)

        return base_ttl

    def _update_ttl(self):
        """Update current TTL based on usage patterns."""
        new_ttl = self._calculate_adaptive_ttl()
        if new_ttl != self._current_ttl:
            old_ttl = self._current_ttl
            self._current_ttl = new_ttl
            print(f"[ProcessRunner] {self.config.name} TTL adjusted: {old_ttl:.0f}s -> {new_ttl:.0f}s")

    def _record_call(self):
        """Record a tool call for TTL calculation."""
        self._call_timestamps.append(time.time())
        self._update_ttl()

    def _default_stderr_handler(self, server_name: str, line: str):
        print(f"[{server_name}][stderr] {line}")

    async def ensure_ready(self, timeout: float = 30.0) -> bool:
        """
        Ensure the process is started and initialized.
        Returns True if ready, False if failed.
        """
        async with self._lock:
            if self._state == ProcessState.READY:
                self._last_used = time.time()
                return True

            if self._state == ProcessState.STOPPED:
                await self._start_process()

            if self._state == ProcessState.RUNNING:
                await self._initialize()

        # Wait for READY state
        start = time.time()
        while time.time() - start < timeout:
            if self._state == ProcessState.READY:
                return True
            if self._state == ProcessState.STOPPED:
                return False
            await asyncio.sleep(0.05)

        return False

    async def _start_process(self):
        """Start the subprocess."""
        self._state = ProcessState.STARTING
        self._spawn_count += 1

        # Build environment
        env = {**os.environ, **self.config.env}

        # Expand environment variables in args
        expanded_args = [
            os.path.expandvars(arg) for arg in self.config.args
        ]

        cmd = [self.config.command] + expanded_args
        print(f"[ProcessRunner] Starting {self.config.name}: {' '.join(cmd)}")

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.cwd,
                env=env,
            )

            self._state = ProcessState.RUNNING
            self._last_used = time.time()
            self._started_at = time.time()

            # Start background tasks
            self._reader_task = asyncio.create_task(self._stdout_reader())
            self._stderr_task = asyncio.create_task(self._stderr_reader())
            self._reaper_task = asyncio.create_task(self._idle_reaper())

            print(f"[ProcessRunner] {self.config.name} started (PID: {self._proc.pid})")

        except Exception as e:
            print(f"[ProcessRunner] Failed to start {self.config.name}: {e}")
            self._state = ProcessState.STOPPED
            self._last_error = str(e)
            raise

    async def _initialize(self):
        """Send initialize request and wait for response."""
        self._state = ProcessState.INITIALIZING
        cold_start_begin = time.time()

        # MCP initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "roots": {"listChanged": True},
                    "sampling": {}
                },
                "clientInfo": {
                    "name": "airis-mcp-gateway",
                    "version": "1.0.0"
                }
            }
        }

        try:
            # Longer timeout for servers that download dependencies on startup (e.g., morphllm)
            response = await self._send_request(init_request, timeout=60.0)

            if "error" in response:
                error_msg = str(response['error'])
                print(f"[ProcessRunner] {self.config.name} initialize failed: {error_msg}")
                self._state = ProcessState.STOPPED
                self._last_error = error_msg
                return

            self._server_info = response.get("result", {})
            print(f"[ProcessRunner] {self.config.name} initialized: {self._server_info.get('serverInfo', {})}")

            # Send notifications/initialized
            await self._send_notification({
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            })

            # Fetch tools list
            await self._fetch_tools()

            # Fetch prompts list (if supported)
            await self._fetch_prompts()

            # Track cold start duration for adaptive TTL
            self._cold_start_time = time.time() - cold_start_begin
            self._update_ttl()

            self._state = ProcessState.READY
            print(f"[ProcessRunner] {self.config.name} is READY with {len(self._tools)} tools, {len(self._prompts)} prompts (cold start: {self._cold_start_time:.1f}s, TTL: {self._current_ttl:.0f}s)")

        except Exception as e:
            print(f"[ProcessRunner] {self.config.name} initialize error: {e}")
            self._state = ProcessState.STOPPED
            self._last_error = str(e)

    async def _fetch_tools(self):
        """Fetch available tools from the server."""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {}
        }

        response = await self._send_request(request, timeout=10.0)

        if "result" in response:
            self._tools = response["result"].get("tools", [])

    async def _fetch_prompts(self):
        """Fetch available prompts from the server."""
        # Only fetch if server declares prompts capability (check key existence, not truthiness)
        capabilities = self._server_info.get("capabilities", {})
        if "prompts" not in capabilities:
            return

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "prompts/list",
            "params": {}
        }

        try:
            response = await self._send_request(request, timeout=10.0)
            if "result" in response:
                self._prompts = response["result"].get("prompts", [])
                print(f"[ProcessRunner] {self.config.name} has {len(self._prompts)} prompts")
        except Exception as e:
            # Not all servers support prompts - this is OK
            print(f"[ProcessRunner] {self.config.name} prompts/list failed (may not be supported): {e}")

    async def get_prompt(self, prompt_name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Get a prompt from this MCP server.

        Returns the JSON-RPC response (with result or error).
        """
        if not await self.ensure_ready():
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": f"Server {self.config.name} failed to initialize"
                }
            }

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "prompts/get",
            "params": {
                "name": prompt_name,
                "arguments": arguments or {}
            }
        }

        return await self._send_request(request, timeout=30.0)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool on this MCP server.

        Returns the JSON-RPC response (with result or error).
        """
        if not await self.ensure_ready():
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": f"Server {self.config.name} failed to initialize"
                }
            }

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        # Track latency and record call for adaptive TTL
        start_time = time.time()
        result = await self._send_request(request, timeout=60.0)
        latency_ms = (time.time() - start_time) * 1000
        self._call_latencies.append(latency_ms)
        self._total_calls += 1
        self._record_call()  # For adaptive TTL

        return result

    async def send_raw_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a raw JSON-RPC request."""
        if not await self.ensure_ready():
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Server {self.config.name} failed to initialize"
                }
            }

        # Assign ID if not present
        if "id" not in request:
            request = {**request, "id": self._next_id()}

        return await self._send_request(request, timeout=60.0)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_request(self, request: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        """Send a request and wait for response."""
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("Process not running")

        request_id = request.get("id")
        if request_id is None:
            raise ValueError("Request must have an id")

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            # Send request
            data = json.dumps(request) + "\n"
            self._proc.stdin.write(data.encode())
            await self._proc.stdin.drain()
            self._last_used = time.time()

            # Wait for response
            return await asyncio.wait_for(future, timeout=timeout)

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Request timeout after {timeout}s"
                }
            }
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }

    async def _send_notification(self, notification: dict[str, Any]):
        """Send a notification (no response expected)."""
        if not self._proc or not self._proc.stdin:
            return

        data = json.dumps(notification) + "\n"
        self._proc.stdin.write(data.encode())
        await self._proc.stdin.drain()
        self._last_used = time.time()

    async def _handle_server_request(self, request: dict[str, Any]):
        """
        Handle server-initiated requests (bidirectional MCP communication).

        MCP servers can request information from clients:
        - roots/list: List available roots (directories/contexts)
        - sampling/createMessage: Request LLM sampling (not supported)
        """
        method = request.get("method", "")
        request_id = request.get("id")

        print(f"[ProcessRunner] {self.config.name} server request: {method} (id={request_id})")

        response: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
        }

        if method == "roots/list":
            # Return empty roots list - we don't expose any directories to MCP servers
            response["result"] = {"roots": []}

        elif method == "sampling/createMessage":
            # We don't support LLM sampling requests from MCP servers
            response["error"] = {
                "code": -32601,
                "message": "Sampling not supported by this client"
            }

        else:
            # Unknown method - return method not found error
            response["error"] = {
                "code": -32601,
                "message": f"Method not found: {method}"
            }

        # Send response
        if self._proc and self._proc.stdin:
            data = json.dumps(response) + "\n"
            self._proc.stdin.write(data.encode())
            await self._proc.stdin.drain()
            print(f"[ProcessRunner] {self.config.name} responded to {method}")

    async def _stdout_reader(self):
        """Read JSON-RPC responses from stdout."""
        if not self._proc or not self._proc.stdout:
            return

        try:
            async for line in self._proc.stdout:
                self._last_used = time.time()
                line_str = line.decode().strip()

                if not line_str:
                    continue

                try:
                    message = json.loads(line_str)
                except json.JSONDecodeError:
                    print(f"[ProcessRunner] {self.config.name} invalid JSON: {line_str[:100]}")
                    continue

                # Handle server-initiated requests (has both "id" and "method")
                if "id" in message and "method" in message:
                    await self._handle_server_request(message)

                # Handle response (has "id" but no "method")
                elif "id" in message:
                    request_id = message["id"]
                    future = self._pending_requests.pop(request_id, None)
                    if future and not future.done():
                        future.set_result(message)

                # Handle server-initiated notifications (has "method" but no "id")
                elif "method" in message:
                    # Log notifications for debugging
                    print(f"[ProcessRunner] {self.config.name} notification: {message.get('method')}")

        except Exception as e:
            if self._state not in (ProcessState.STOPPING, ProcessState.STOPPED):
                print(f"[ProcessRunner] {self.config.name} stdout reader error: {e}")

    async def _stderr_reader(self):
        """Read stderr and forward to handler."""
        if not self._proc or not self._proc.stderr:
            return

        try:
            async for line in self._proc.stderr:
                line_str = line.decode().rstrip()
                if line_str:
                    self.on_stderr(self.config.name, line_str)
        except Exception as e:
            if self._state not in (ProcessState.STOPPING, ProcessState.STOPPED):
                print(f"[ProcessRunner] {self.config.name} stderr reader error: {e}")

    async def _idle_reaper(self):
        """Kill process after idle timeout (uses adaptive TTL)."""
        while self._state not in (ProcessState.STOPPING, ProcessState.STOPPED):
            await asyncio.sleep(5)

            if self._state == ProcessState.READY:
                idle_time = time.time() - self._last_used
                # Use adaptive TTL if enabled, otherwise fall back to config
                effective_ttl = self._current_ttl if self.config.adaptive_ttl_enabled else self.config.idle_timeout
                if idle_time > effective_ttl:
                    print(f"[ProcessRunner] {self.config.name} idle for {idle_time:.0f}s (TTL: {effective_ttl:.0f}s), stopping")
                    self._idle_kill_count += 1
                    await self.stop()
                    return

    async def stop(self):
        """Stop the process gracefully."""
        if self._state in (ProcessState.STOPPING, ProcessState.STOPPED):
            return

        self._state = ProcessState.STOPPING

        # Cancel pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(RuntimeError("Process stopping"))
        self._pending_requests.clear()

        # Cancel background tasks
        for task in [self._reader_task, self._stderr_task, self._reaper_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Terminate process
        if self._proc:
            try:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
            except ProcessLookupError:
                pass

            print(f"[ProcessRunner] {self.config.name} stopped")

        self._proc = None
        self._state = ProcessState.STOPPED
        self._tools = []
        self._prompts = []
        self._server_info = {}
        self._started_at = None

    def get_metrics(self) -> dict[str, Any]:
        """
        Get SRE-grade metrics for this process.

        Returns:
            {
                "uptime_ms": int or None,
                "spawn_count": int,
                "idle_kill_count": int,
                "total_calls": int,
                "latency_p50_ms": float or None,
                "latency_p95_ms": float or None,
                "latency_p99_ms": float or None,
                "memory_rss_mb": float or None,
                "cpu_percent": float or None,
                "last_error": str or None,
                "pid": int or None,
                "adaptive_ttl": {...}  # Adaptive TTL metrics
            }
        """
        metrics: dict[str, Any] = {
            "uptime_ms": None,
            "spawn_count": self._spawn_count,
            "idle_kill_count": self._idle_kill_count,
            "total_calls": self._total_calls,
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "latency_p99_ms": None,
            "memory_rss_mb": None,
            "cpu_percent": None,
            "last_error": self._last_error,
            "pid": None,
            # Adaptive TTL metrics
            "adaptive_ttl": {
                "enabled": self.config.adaptive_ttl_enabled,
                "current_ttl_s": round(self._current_ttl, 1),
                "min_ttl_s": self.config.min_ttl,
                "max_ttl_s": self.config.max_ttl,
                "cold_start_time_s": round(self._cold_start_time, 2) if self._cold_start_time else None,
                "recent_calls": len([ts for ts in self._call_timestamps if ts > time.time() - self.config.ttl_window]),
            },
        }

        # Calculate uptime
        if self._started_at and self._state == ProcessState.READY:
            metrics["uptime_ms"] = int((time.time() - self._started_at) * 1000)

        # Calculate latency percentiles
        if self._call_latencies:
            sorted_latencies = sorted(self._call_latencies)
            n = len(sorted_latencies)
            metrics["latency_p50_ms"] = round(sorted_latencies[int(n * 0.50)], 2)
            metrics["latency_p95_ms"] = round(sorted_latencies[int(n * 0.95)], 2)
            metrics["latency_p99_ms"] = round(sorted_latencies[min(int(n * 0.99), n - 1)], 2)

        # Get process metrics if psutil available and process running
        if HAS_PSUTIL and self._proc and self._proc.pid:
            try:
                proc = psutil.Process(self._proc.pid)
                metrics["pid"] = self._proc.pid
                metrics["memory_rss_mb"] = round(proc.memory_info().rss / 1024 / 1024, 2)
                metrics["cpu_percent"] = round(proc.cpu_percent(interval=0.1), 2)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        elif self._proc and self._proc.pid:
            metrics["pid"] = self._proc.pid

        return metrics
