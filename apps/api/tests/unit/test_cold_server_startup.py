"""
Real COLD-server startup integration test (issue #195).

tests/e2e/test_dynamic_mcp_e2e.py::TestProcessTools::test_list_tools_all_modes
is permanently `@pytest.mark.skip(reason="COLD server startup takes too long
for CI")`, so the auto-enable -> spawn -> initialize handshake ->
tools/call machinery (ProcessManager/ProcessRunner + DynamicMCP's
auto_discover_and_execute) had zero CI coverage — the most failure-prone
runtime path in the gateway was untested by every green CI run.

This test drives that path for real (no mocks): it registers a genuine COLD
server config pointing at tests/fixtures/mini_mcp_server.py (a tiny stdio
MCP server), then calls the real DynamicMCP.auto_discover_and_execute() and
asserts the subprocess actually spawned, completed the real event-driven
MCP handshake (PR #202 — no fixed sleeps), and executed a tool call.

Runs in the `test-python` CI job (tests/unit), no Docker required — the
"server" is just `python tests/fixtures/mini_mcp_server.py`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from app.core.dynamic_mcp import DynamicMCP
from app.core.mcp_config_loader import McpServerConfig, ServerMode
from app.core.process_manager import ProcessManager
from app.core.process_runner import ProcessRunner, ProcessState

FIXTURE_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mini_mcp_server.py"

# Generous timeout for the real spawn + handshake; the underlying wait is
# event-driven (asyncio.Condition, see process_runner.py), not polled, so a
# healthy run completes in well under a second.
STARTUP_TIMEOUT = 30.0


def _make_cold_config(name: str = "mini-mcp") -> McpServerConfig:
    assert FIXTURE_SERVER.is_file(), f"mini MCP server fixture missing: {FIXTURE_SERVER}"
    return McpServerConfig(
        name=name,
        server_type="process",
        command=sys.executable,
        args=[str(FIXTURE_SERVER)],
        env={},
        enabled=False,  # COLD-lazy: not started until auto-enabled
        mode=ServerMode.COLD,
        tools_index=[{"name": "echo", "description": "Echo back the given message"}],
    )


def _wire_process_manager(pm: ProcessManager) -> None:
    """Same wiring as test_cold_tool_auto_discovery.py: expose configs
    injected directly (bypassing initialize()'s mcp-config.json load)."""
    pm.get_server_names = lambda: list(pm._server_configs.keys())
    pm.is_process_server = lambda name: name in pm._runners


@pytest_asyncio.fixture
async def cold_manager():
    """A ProcessManager wired with one real COLD server (mini_mcp_server.py)."""
    pm = ProcessManager(idle_timeout=120)
    pm._initialized = True
    config = _make_cold_config()
    pm._server_configs[config.name] = config
    runner = ProcessRunner(
        config.to_process_config(pm._idle_timeout),
        on_idle_kill=pm._handle_idle_kill,
    )
    pm._runners[config.name] = runner
    _wire_process_manager(pm)

    try:
        yield pm, config.name
    finally:
        # Reap the real subprocess regardless of test outcome.
        await runner.stop()


@pytest.mark.asyncio
async def test_cold_auto_enable_spawns_real_subprocess_and_executes_tool(cold_manager):
    """End-to-end: auto-discover the COLD tool, auto-enable its server, spawn
    the real subprocess, complete the real MCP handshake, and call the tool —
    the exact path the permanently-skipped e2e test was meant to cover."""
    pm, server_name = cold_manager
    dmcp = DynamicMCP()

    assert pm._server_configs[server_name].enabled is False, "server must start COLD/disabled"

    result = await asyncio.wait_for(
        dmcp.auto_discover_and_execute("echo", {"message": "hello"}, pm),
        timeout=STARTUP_TIMEOUT,
    )

    assert result is not None, "auto_discover_and_execute returned None — tool/server lookup failed"
    assert "error" not in result, f"tool call returned an error: {result.get('error')}"
    assert result["result"]["content"][0]["text"] == "echo: hello"

    # The server must have been genuinely auto-enabled (not just looked up).
    assert pm._server_configs[server_name].enabled is True

    # Prove a real subprocess was spawned and completed the real handshake —
    # not a stub/mocked response.
    runner = pm.get_runner(server_name)
    assert runner.state == ProcessState.READY
    assert runner._proc is not None
    assert runner._proc.pid is not None
    assert runner._proc.returncode is None, "subprocess exited instead of staying up"
    assert any(t.get("name") == "echo" for t in runner.tools), "tools/list did not return the echo tool"


@pytest.mark.asyncio
async def test_cold_server_already_enabled_reuses_running_process(cold_manager):
    """Calling twice must not re-spawn a second subprocess for the same server."""
    pm, server_name = cold_manager
    dmcp = DynamicMCP()

    first = await asyncio.wait_for(
        dmcp.auto_discover_and_execute("echo", {"message": "one"}, pm),
        timeout=STARTUP_TIMEOUT,
    )
    runner = pm.get_runner(server_name)
    first_pid = runner._proc.pid

    second = await asyncio.wait_for(
        dmcp.auto_discover_and_execute("echo", {"message": "two"}, pm),
        timeout=STARTUP_TIMEOUT,
    )

    assert first["result"]["content"][0]["text"] == "echo: one"
    assert second["result"]["content"][0]["text"] == "echo: two"
    assert runner._proc.pid == first_pid, "second call spawned a new subprocess instead of reusing it"
