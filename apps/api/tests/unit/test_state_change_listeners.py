"""
Regression tests for ProcessManager HOT-set state-change listeners.

The manager fires a listener whenever a server enters or leaves the HOT
set so the proxy layer can emit notifications/tools/list_changed to
connected clients. These tests pin:

- subscribe / unsubscribe semantics
- enable_server fires ENABLED only on a real transition, not when the
  server was already enabled
- disable_server fires DISABLED only on a real transition
- _handle_idle_kill fires IDLE_KILLED and drops the cached tool routing
  for the killed server
- listener exceptions are swallowed so one bad listener cannot break
  the manager
"""

from __future__ import annotations

import pytest

from app.core.mcp_config_loader import McpServerConfig, ServerMode, ServerType
from app.core.process_manager import (
    STATE_CHANGE_DISABLED,
    STATE_CHANGE_ENABLED,
    STATE_CHANGE_IDLE_KILLED,
    ProcessManager,
)


def _make_config(name: str, enabled: bool = True) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        server_type=ServerType.PROCESS,
        command="echo",
        args=[],
        env={},
        enabled=enabled,
        mode=ServerMode.COLD,
    )


@pytest.mark.asyncio
async def test_add_and_remove_listener():
    pm = ProcessManager()
    events: list[tuple[str, str]] = []

    async def listener(event: str, name: str) -> None:
        events.append((event, name))

    pm.add_state_change_listener(listener)
    pm.add_state_change_listener(listener)  # duplicate — must be deduped
    assert pm._state_change_listeners == [listener]

    pm.remove_state_change_listener(listener)
    assert pm._state_change_listeners == []


@pytest.mark.asyncio
async def test_enable_server_fires_only_on_transition():
    pm = ProcessManager()
    pm._server_configs["stripe"] = _make_config("stripe", enabled=False)

    events: list[tuple[str, str]] = []

    async def listener(event: str, name: str) -> None:
        events.append((event, name))

    pm.add_state_change_listener(listener)

    assert await pm.enable_server("stripe") is True
    assert events == [(STATE_CHANGE_ENABLED, "stripe")]

    # Enabling again is a no-op for listeners.
    assert await pm.enable_server("stripe") is True
    assert events == [(STATE_CHANGE_ENABLED, "stripe")]


@pytest.mark.asyncio
async def test_disable_server_fires_only_on_transition():
    pm = ProcessManager()
    pm._server_configs["stripe"] = _make_config("stripe", enabled=True)

    events: list[tuple[str, str]] = []

    async def listener(event: str, name: str) -> None:
        events.append((event, name))

    pm.add_state_change_listener(listener)

    assert await pm.disable_server("stripe") is True
    assert events == [(STATE_CHANGE_DISABLED, "stripe")]

    # Disabling again is a no-op for listeners.
    assert await pm.disable_server("stripe") is True
    assert events == [(STATE_CHANGE_DISABLED, "stripe")]


@pytest.mark.asyncio
async def test_handle_idle_kill_fires_and_clears_routing():
    pm = ProcessManager()
    pm._server_configs["stripe"] = _make_config("stripe", enabled=True)
    pm._tool_to_server = {
        "stripe_create_customer": "stripe",
        "tavily_search": "tavily",
    }
    pm._prompt_to_server = {"stripe_dunning": "stripe"}

    events: list[tuple[str, str]] = []

    async def listener(event: str, name: str) -> None:
        events.append((event, name))

    pm.add_state_change_listener(listener)

    await pm._handle_idle_kill("stripe")

    assert events == [(STATE_CHANGE_IDLE_KILLED, "stripe")]
    assert pm._tool_to_server == {"tavily_search": "tavily"}, (
        "idle-kill must drop the killed server's cached tool routing so the "
        "next tools/list reflects the smaller HOT set"
    )
    assert pm._prompt_to_server == {}


@pytest.mark.asyncio
async def test_listener_exception_is_swallowed():
    pm = ProcessManager()
    pm._server_configs["stripe"] = _make_config("stripe", enabled=False)

    call_log: list[str] = []

    async def noisy(event: str, name: str) -> None:
        call_log.append("noisy")
        raise RuntimeError("boom")

    async def healthy(event: str, name: str) -> None:
        call_log.append("healthy")

    pm.add_state_change_listener(noisy)
    pm.add_state_change_listener(healthy)

    # Must not raise even though `noisy` does.
    assert await pm.enable_server("stripe") is True
    assert call_log == ["noisy", "healthy"]
