"""
Tests for per-server health surfacing (issue #197).

Today, upstream server failures (missing API key, dead command, exception
during tool listing) are swallowed by broad `except Exception: log &
continue` sites in `dynamic_mcp.py` / `process_manager.py`. A misconfigured
server just disappears from `tools/list` / `airis-find` with only a log
line — the LLM sees "some tools are missing" with no cause.

These tests pin the fix: a per-server `ServerHealth` record on
`ProcessManager`, surfaced via `DynamicMCP.find()` annotations and a new
`GET /health/servers` endpoint, with `airis-exec` error enrichment.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.dynamic_mcp import DynamicMCP, ToolInfo
from app.core.mcp_config_loader import McpServerConfig, ServerMode
from app.core.process_manager import ProcessManager, ServerHealth
from app.core.process_runner import ProcessState


# ── Helpers ──


def _make_config(name: str, *, enabled: bool = True, mode=ServerMode.COLD,
                  policy_disabled: bool = False) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        server_type="process",
        command="uvx",
        args=["test-server"],
        env={},
        enabled=enabled,
        policy_disabled=policy_disabled,
        mode=mode,
        tools_index=[],
    )


class _FakeRunner:
    """Minimal ProcessRunner stand-in whose first ensure_ready_with_error()
    call fails (simulating a dead command / missing env var), then
    succeeds on the next call (simulating the operator fixing the config)."""

    def __init__(self, error_message: str = "missing API key: STRIPE_KEY not set"):
        self.state = ProcessState.STOPPED
        self.tools = [{"name": "create_customer", "description": "Create a customer"}]
        self._error_message = error_message
        self._attempts = 0

    async def ensure_ready_with_error(self, timeout: float = 30.0):
        self._attempts += 1
        if self._attempts == 1:
            self.state = ProcessState.STOPPED
            return (False, self._error_message)
        self.state = ProcessState.READY
        return (True, None)


# ── ProcessManager: health recording on start failure / recovery ──


@pytest.mark.asyncio
async def test_start_failure_records_health_with_error():
    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["stripe"] = _make_config("stripe")
    pm._runners["stripe"] = _FakeRunner()

    tools = await pm._list_tools_for_server("stripe")

    assert tools == []
    health = pm.get_server_health("stripe")
    assert health.status == "start_failed"
    assert health.last_error is not None
    assert "missing API key" in health.last_error
    assert health.last_checked is not None


@pytest.mark.asyncio
async def test_subsequent_success_resets_health_to_ok():
    """A server that fails once and then starts cleanly must not stay
    flagged as broken forever — this is the isolation guarantee: one bad
    attempt must not permanently poison discovery once fixed."""
    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["stripe"] = _make_config("stripe")
    runner = _FakeRunner()
    pm._runners["stripe"] = runner

    await pm._list_tools_for_server("stripe")  # fails
    assert pm.get_server_health("stripe").status == "start_failed"

    tools = await pm._list_tools_for_server("stripe")  # now succeeds

    assert len(tools) == 1
    health = pm.get_server_health("stripe")
    assert health.status == "ok"
    assert health.last_error is None


def test_error_text_truncated_to_avoid_unbounded_memory():
    pm = ProcessManager()
    pm.record_health("stripe", "start_failed", "x" * 5000)

    health = pm.get_server_health("stripe")
    assert len(health.last_error) <= 300


def test_unrecorded_server_defaults_to_not_started():
    pm = ProcessManager()
    health = pm.get_server_health("never-touched")
    assert health.status == "not_started"
    assert health.last_error is None


# ── DynamicMCP.find(): silent-vanish regression guard ──


def test_airis_find_annotates_tools_for_failing_server():
    """The core regression guard: a server's indexed tools stay discoverable
    (they don't vanish) AND carry a server_status/server_error annotation
    once its health record shows a failure — instead of looking identical
    to a healthy server's tools."""
    dmcp = DynamicMCP()
    dmcp._tools["create_customer"] = ToolInfo(
        name="create_customer",
        server="stripe",
        description="Create a Stripe customer",
        input_schema={},
        source="index",
    )
    dmcp._tool_to_server["create_customer"] = "stripe"

    pm = ProcessManager()
    pm.record_health("stripe", "start_failed", "missing API key: STRIPE_KEY not set")

    results = dmcp.find(query="stripe", process_manager=pm)

    matches = [t for t in results["tools"] if t["name"] == "create_customer"]
    assert matches, "tool must still be discoverable, not silently vanish"
    entry = matches[0]
    assert entry["server_status"] == "start_failed"
    assert "missing API key" in entry["server_error"]


def test_airis_find_does_not_annotate_healthy_server():
    dmcp = DynamicMCP()
    dmcp._tools["create_customer"] = ToolInfo(
        name="create_customer",
        server="stripe",
        description="Create a Stripe customer",
        input_schema={},
        source="index",
    )
    dmcp._tool_to_server["create_customer"] = "stripe"

    pm = ProcessManager()
    pm.record_health("stripe", "ok")

    results = dmcp.find(query="stripe", process_manager=pm)

    entry = [t for t in results["tools"] if t["name"] == "create_customer"][0]
    assert "server_status" not in entry
    assert "server_error" not in entry


def test_airis_find_without_process_manager_is_unannotated_backward_compat():
    """find() without process_manager (existing callers) behaves exactly
    as before — no annotation keys added."""
    dmcp = DynamicMCP()
    dmcp._tools["create_customer"] = ToolInfo(
        name="create_customer", server="stripe", description="Create customer",
        input_schema={}, source="index",
    )
    dmcp._tool_to_server["create_customer"] = "stripe"

    results = dmcp.find(query="stripe")

    entry = results["tools"][0]
    assert "server_status" not in entry


# ── GET /health/servers ──


def test_health_servers_endpoint_returns_map(monkeypatch):
    from app.main import app

    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["stripe"] = _make_config("stripe", mode=ServerMode.COLD, enabled=False)
    pm._runners["stripe"] = _FakeRunner()
    pm.record_health("stripe", "start_failed", "boom")

    monkeypatch.setattr("app.main.get_process_manager", lambda: pm)

    client = TestClient(app)
    resp = client.get("/health/servers")

    assert resp.status_code == 200
    body = resp.json()
    assert "stripe" in body["servers"]
    entry = body["servers"]["stripe"]
    assert entry["status"] == "start_failed"
    assert entry["last_error"] == "boom"
    assert entry["mode"] == "cold"
    assert entry["enabled"] is False
    assert entry["policy_disabled"] is False
    assert entry["last_checked"] is not None


def test_health_servers_endpoint_reports_policy_disabled(monkeypatch):
    from app.main import app

    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["supabase"] = _make_config(
        "supabase", mode=ServerMode.COLD, enabled=False, policy_disabled=True
    )
    pm._runners["supabase"] = _FakeRunner()
    pm.record_health("supabase", "policy_disabled")

    monkeypatch.setattr("app.main.get_process_manager", lambda: pm)

    client = TestClient(app)
    resp = client.get("/health/servers")

    entry = resp.json()["servers"]["supabase"]
    assert entry["policy_disabled"] is True
    assert entry["status"] == "policy_disabled"


# ── ProcessManager.call_tool_on_server: enrichment source ──


@pytest.mark.asyncio
async def test_call_tool_on_server_records_start_failure_health():
    """airis-exec calls call_tool_on_server directly (bypassing
    _list_tools_for_server). This must also record health so the JSON-RPC
    error can be enriched with the real cause."""
    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["stripe"] = _make_config("stripe")

    class _FailingRunner:
        state = ProcessState.STOPPED
        _last_error = "missing API key: STRIPE_KEY not set"

        async def call_tool(self, tool_name, arguments):
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Server stripe failed to initialize"},
            }

    pm._runners["stripe"] = _FailingRunner()

    result = await pm.call_tool_on_server("stripe", "create_customer", {})

    assert "error" in result
    health = pm.get_server_health("stripe")
    assert health.status == "start_failed"
    assert health.last_error == "missing API key: STRIPE_KEY not set"
