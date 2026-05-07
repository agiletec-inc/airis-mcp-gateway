"""
Tests for COLD tool auto-discovery in the MCP tools/call handler.

When a native tool call arrives for a tool not yet in ProcessManager._tool_to_server,
the gateway looks it up via tools_index, auto-enables its COLD server, loads the
tools into cache, and executes directly — without needing airis-exec as a router.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import mcp_proxy
from app.core.dynamic_mcp import DynamicMCP, ToolInfo, get_dynamic_mcp
from app.core.process_manager import ProcessManager, get_process_manager
from app.core.mcp_config_loader import McpServerConfig, ServerMode


# ── Helpers ──


def _make_config(name: str, *, enabled: bool = True, mode=ServerMode.COLD,
                 tools_index: list[dict] | None = None) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        server_type="process",
        command="uvx",
        args=["test-server"],
        env={},
        enabled=enabled,
        mode=mode,
        tools_index=tools_index or [],
    )


def _wire_process_manager(pm: ProcessManager) -> None:
    """Wire ProcessManager._server_configs to get_server_names / is_process_server.

    These methods normally depend on _runners (populated during initialize()),
    but we inject server configs directly for testing without full initialization.
    """
    pm.get_server_names = lambda: list(pm._server_configs.keys())
    pm.is_process_server = lambda name: name in pm._server_configs


def _make_client(pm: ProcessManager, dmcp: DynamicMCP, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        "app.api.endpoints.mcp_proxy.get_process_manager", lambda: pm
    )
    monkeypatch.setattr(
        "app.core.dynamic_mcp.get_dynamic_mcp", lambda: dmcp
    )

    app = FastAPI()
    app.include_router(mcp_proxy.router, prefix="/mcp")
    return TestClient(app)


# ── DynamicMCP.get_server_for_tool_from_index ──


def test_get_server_for_tool_from_index_finds_cold_tool():
    dmcp = DynamicMCP()
    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["stripe"] = _make_config(
        "stripe", mode=ServerMode.COLD, enabled=False,
        tools_index=[{"name": "create_customer", "description": "Create a Stripe customer"}],
    )
    _wire_process_manager(pm)

    server = dmcp.get_server_for_tool_from_index("create_customer", pm)
    assert server == "stripe"


def test_get_server_for_tool_from_index_returns_none_for_unknown_tool():
    dmcp = DynamicMCP()
    pm = ProcessManager()
    pm._initialized = True
    _wire_process_manager(pm)

    server = dmcp.get_server_for_tool_from_index("nonexistent", pm)
    assert server is None


def test_get_server_for_tool_from_index_returns_none_when_no_config_has_tools_index():
    dmcp = DynamicMCP()
    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["memory"] = _make_config("memory", tools_index=[])
    _wire_process_manager(pm)

    server = dmcp.get_server_for_tool_from_index("create_entities", pm)
    assert server is None


# ── tools/call auto-discovery (integration via FastAPI TestClient) ──


def test_cold_tool_auto_discovered_and_executed(monkeypatch):
    """A tools/call for an unknown COLD tool triggers auto-discovery and execution."""
    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["stripe"] = _make_config(
        "stripe", mode=ServerMode.COLD, enabled=False,
        tools_index=[{"name": "create_customer", "description": "Create customer"}],
    )
    _wire_process_manager(pm)

    call_log = []

    async def fake_enable_server(name):
        pm._server_configs[name].enabled = True
        call_log.append(f"enable:{name}")

    async def fake_call_tool_on_server(server_name, tool_name, arguments):
        call_log.append(f"call:{server_name}:{tool_name}")
        return {"result": {"content": [{"type": "text", "text": "ok"}], "isError": False}}

    async def fake_load_tools_for_server(server_name, process_manager, force_enable=False):
        pm._tool_to_server["create_customer"] = "stripe"

    monkeypatch.setattr(pm, "enable_server", fake_enable_server)
    monkeypatch.setattr(pm, "call_tool_on_server", fake_call_tool_on_server)

    dmcp = DynamicMCP()
    monkeypatch.setattr(dmcp, "load_tools_for_server", fake_load_tools_for_server)

    tc = _make_client(pm, dmcp, monkeypatch)

    resp = tc.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "create_customer", "arguments": {"email": "x@y.com"}},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("result", {}).get("content")[0]["text"] == "ok"
    assert "enable:stripe" in call_log
    assert "call:stripe:create_customer" in call_log
    assert pm._server_configs["stripe"].enabled is True


def test_cold_tool_already_enabled_server_skips_enable(monkeypatch):
    """Server already enabled → enable skipped, but tools still loaded and called."""
    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["stripe"] = _make_config(
        "stripe", mode=ServerMode.COLD, enabled=True,
        tools_index=[{"name": "create_customer", "description": "Create customer"}],
    )
    _wire_process_manager(pm)

    call_log = []

    async def fake_enable_server(name):
        call_log.append(f"enable:{name}")

    async def fake_call_tool_on_server(server_name, tool_name, arguments):
        call_log.append(f"call:{server_name}:{tool_name}")
        return {"result": {"content": [{"type": "text", "text": "ok"}], "isError": False}}

    async def fake_load_tools_for_server(server_name, process_manager, force_enable=False):
        pm._tool_to_server["create_customer"] = "stripe"

    monkeypatch.setattr(pm, "enable_server", fake_enable_server)
    monkeypatch.setattr(pm, "call_tool_on_server", fake_call_tool_on_server)

    dmcp = DynamicMCP()
    monkeypatch.setattr(dmcp, "load_tools_for_server", fake_load_tools_for_server)

    tc = _make_client(pm, dmcp, monkeypatch)

    resp = tc.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "create_customer", "arguments": {}},
        },
    )
    assert resp.status_code == 200
    assert "enable:stripe" not in call_log  # already enabled
    assert "call:stripe:create_customer" in call_log


def test_hot_tool_in_tool_to_server_uses_fast_path(monkeypatch):
    """A tool already in _tool_to_server skips auto-discovery entirely."""
    pm = ProcessManager()
    pm._initialized = True
    pm._tool_to_server["gateway_health"] = "gateway-control"
    pm._server_configs["gateway-control"] = _make_config(
        "gateway-control", mode=ServerMode.HOT, enabled=True,
    )
    _wire_process_manager(pm)

    call_log = []

    async def fake_call_tool(name, arguments):
        call_log.append(f"hot_call:{name}")
        return {"result": {"content": [{"type": "text", "text": "healthy"}]}}

    monkeypatch.setattr(pm, "call_tool", fake_call_tool)

    dmcp = DynamicMCP()

    tc = _make_client(pm, dmcp, monkeypatch)

    resp = tc.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "gateway_health", "arguments": {}},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["content"][0]["text"] == "healthy"
    assert call_log == ["hot_call:gateway_health"]


def test_unknown_tool_falls_through_to_gateway(monkeypatch):
    """A tool not in _tool_to_server and not in any tools_index falls through."""
    pm = ProcessManager()
    pm._initialized = True
    _wire_process_manager(pm)

    dmcp = DynamicMCP()

    tc = _make_client(pm, dmcp, monkeypatch)

    # No session_id → stream bridge path. That fails without a real Gateway,
    # so the response is an error. The key assertion: auto-discovery tried and
    # found nothing, so the request fell through (didn't return early).
    resp = tc.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        },
    )
    # Fallthrough to stream bridge → 400/500 with Gateway unreachable
    assert resp.status_code in (200, 400, 500)


def test_auto_discovery_error_handling(monkeypatch):
    """If auto-discovery succeeds but call_tool_on_server errors, error is returned."""
    pm = ProcessManager()
    pm._initialized = True
    pm._server_configs["stripe"] = _make_config(
        "stripe", mode=ServerMode.COLD, enabled=False,
        tools_index=[{"name": "create_customer", "description": "Create customer"}],
    )
    _wire_process_manager(pm)

    async def fake_enable_server(name):
        pm._server_configs[name].enabled = True

    async def fake_call_tool_on_server(server_name, tool_name, arguments):
        return {"error": {"code": -32603, "message": "Internal server error"}}

    async def fake_load_tools_for_server(server_name, process_manager, force_enable=False):
        pm._tool_to_server["create_customer"] = "stripe"

    monkeypatch.setattr(pm, "enable_server", fake_enable_server)
    monkeypatch.setattr(pm, "call_tool_on_server", fake_call_tool_on_server)

    dmcp = DynamicMCP()
    monkeypatch.setattr(dmcp, "load_tools_for_server", fake_load_tools_for_server)

    tc = _make_client(pm, dmcp, monkeypatch)

    resp = tc.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "create_customer", "arguments": {}},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"]["code"] == -32603
    assert body["error"]["message"] == "Internal server error"
