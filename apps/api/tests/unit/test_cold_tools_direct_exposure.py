"""
Tests for direct COLD-tool exposure in tools/list (issue #198).

Background (already true before this change): a bare tools/call for a COLD
tool already works in one hop via DynamicMCP.auto_discover_and_execute
(tools_index lookup + auto-enable + self-heal on -32602). The only missing
piece was that clients could not learn COLD tool names from tools/list at
all, forcing them through airis-find -> airis-exec (2-3 hops).

This module tests apply_schema_partitioning()'s new behavior: every
discoverable (non policy_disabled) COLD server's tools_index entries are
now advertised directly in tools/list with a lazy stub schema
({"type": "object"}), using the bare tool name exactly as
DynamicMCP.auto_discover_and_execute resolves it.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.endpoints import tool_shaping
from app.core.config import settings
from app.core.dynamic_mcp import DynamicMCP
from app.core.mcp_config_loader import McpServerConfig, ServerMode
from app.core.process_manager import ProcessManager

REPO_ROOT = Path(__file__).resolve().parents[4]


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_config(
    name: str,
    *,
    enabled: bool = True,
    mode: ServerMode = ServerMode.COLD,
    tools_index: list[dict] | None = None,
    policy_disabled: bool = False,
) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        server_type="process",
        command="uvx",
        args=["test-server"],
        env={},
        enabled=enabled,
        policy_disabled=policy_disabled,
        mode=mode,
        tools_index=tools_index or [],
    )


def _wire_process_manager(pm: ProcessManager) -> None:
    """See test_cold_tool_auto_discovery.py — same wiring pattern."""
    pm.get_server_names = lambda: list(pm._server_configs.keys())
    pm.is_process_server = lambda name: name in pm._server_configs


def _build_pm(monkeypatch, *, hot_servers=None) -> ProcessManager:
    pm = ProcessManager()
    pm._initialized = True
    _wire_process_manager(pm)
    pm.get_hot_servers = lambda: list(hot_servers or [])
    pm.list_tools = AsyncMock(return_value=[])
    monkeypatch.setattr(tool_shaping, "get_process_manager", lambda: pm)
    monkeypatch.setattr(tool_shaping, "get_dynamic_mcp", lambda: DynamicMCP())
    monkeypatch.setattr(settings, "DYNAMIC_MCP", True)
    monkeypatch.setattr(settings, "SCHEMA_MODE", "lazy")
    monkeypatch.setattr(settings, "COLD_TOOLS_IN_LIST", True)
    return pm


async def _list_tools(pm) -> list[dict]:
    data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    out = await tool_shaping.apply_schema_partitioning(data)
    return out["result"]["tools"]


# ── Core behavior ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cold_server_tools_appear_in_tools_list_with_stub_schema(monkeypatch):
    pm = _build_pm(monkeypatch)
    pm._server_configs["stripe"] = _make_config(
        "stripe",
        enabled=False,
        tools_index=[
            {"name": "create_customer", "description": "Create a Stripe customer"},
            {"name": "list_charges", "description": "List Stripe charges"},
        ],
    )

    tools = {t["name"]: t for t in await _list_tools(pm)}

    assert "create_customer" in tools, tools.keys()
    assert "list_charges" in tools, tools.keys()
    assert tools["create_customer"]["inputSchema"] == {"type": "object"}
    assert tools["create_customer"]["description"]


@pytest.mark.asyncio
async def test_policy_disabled_server_tools_are_not_listed(monkeypatch):
    """supabase / mindbase (policy_disabled) must never be advertised."""
    pm = _build_pm(monkeypatch)
    pm._server_configs["supabase"] = _make_config(
        "supabase",
        enabled=False,
        policy_disabled=True,
        tools_index=[{"name": "query", "description": "Execute a SQL query"}],
    )
    pm._server_configs["mindbase"] = _make_config(
        "mindbase",
        enabled=False,
        policy_disabled=True,
        tools_index=[{"name": "conversation_search", "description": "Search conversations"}],
    )

    tools = {t["name"] for t in await _list_tools(pm)}

    assert "query" not in tools
    assert "conversation_search" not in tools


@pytest.mark.asyncio
async def test_cold_tools_in_list_false_restores_old_meta_tool_only_listing(monkeypatch):
    pm = _build_pm(monkeypatch)
    monkeypatch.setattr(settings, "COLD_TOOLS_IN_LIST", False)
    pm._server_configs["stripe"] = _make_config(
        "stripe",
        enabled=False,
        tools_index=[{"name": "create_customer", "description": "Create a Stripe customer"}],
    )

    tools = {t["name"] for t in await _list_tools(pm)}

    assert "create_customer" not in tools
    # Meta-tools are still present.
    assert "airis-find" in tools
    assert "airis-exec" in tools


@pytest.mark.asyncio
async def test_collision_keeps_first_occurrence_and_does_not_crash(monkeypatch):
    pm = _build_pm(monkeypatch)
    pm._server_configs["stripe"] = _make_config(
        "stripe",
        enabled=False,
        tools_index=[{"name": "shared_name", "description": "From stripe"}],
    )
    pm._server_configs["github"] = _make_config(
        "github",
        enabled=True,
        tools_index=[{"name": "shared_name", "description": "From github"}],
    )

    tools = [t for t in await _list_tools(pm) if t["name"] == "shared_name"]
    assert len(tools) == 1, "colliding tool name must appear exactly once"


# ── Completeness canary ──────────────────────────────────────────────────


def _discoverable_cold_index_names_from_registry() -> set[str]:
    """Every tools_index name on a COLD, non policy_disabled server in the
    tracked registry mirror. Mirrors is_discoverable()'s policy_disabled-only
    gate."""
    data = json.loads((REPO_ROOT / "mcp-config.json.example").read_text())
    names: set[str] = set()
    for cfg in data["mcpServers"].values():
        if cfg.get("mode") != "cold":
            continue
        if cfg.get("policy_disabled"):
            continue
        for entry in cfg.get("tools_index") or []:
            if entry.get("name"):
                names.add(entry["name"])
    return names


@pytest.mark.asyncio
async def test_every_discoverable_cold_indexed_tool_is_listed(monkeypatch):
    """Completeness canary: load the real mcp-config.json.example registry
    through mcp_config_loader and assert every discoverable COLD indexed
    tool name shows up in the produced tools/list. Prevents future
    partial-exposure drift (e.g. someone gating on a subset of servers)."""
    from app.core.mcp_config_loader import load_mcp_config

    parsed = load_mcp_config(str(REPO_ROOT / "mcp-config.json.example"))

    pm = _build_pm(monkeypatch)
    pm._server_configs = dict(parsed)

    listed_names = {t["name"] for t in await _list_tools(pm)}
    expected = _discoverable_cold_index_names_from_registry()

    missing = expected - listed_names
    assert not missing, f"COLD indexed tools missing from tools/list: {missing}"


@pytest.mark.asyncio
async def test_advertised_cold_name_resolves_to_the_server_it_was_attributed_to(
    monkeypatch,
):
    """Resolver/collector parity canary (issue #198 review finding 1): every
    COLD tool name advertised in tools/list must resolve, via
    DynamicMCP.get_server_for_tool_from_index, to a discoverable server —
    and specifically the SAME server the collector attributed it to.

    Regression this guards: `query` is indexed by both `supabase`
    (policy_disabled) and `postgres` (discoverable) in the real registry.
    The collector skips supabase and advertises `query` for postgres, but a
    resolver that iterates ALL servers (including policy_disabled ones)
    without the same is_discoverable() filter can return supabase first —
    so calling the advertised name silently 1-hops into the wrong,
    policy-disabled server instead of the one that was listed.
    """
    from app.core.mcp_config_loader import is_discoverable, load_mcp_config

    parsed = load_mcp_config(str(REPO_ROOT / "mcp-config.json.example"))

    pm = _build_pm(monkeypatch)
    pm._server_configs = dict(parsed)

    # Mirror collect_cold_discoverable_tools()'s exact attribution: iterate
    # servers in the same order, first occurrence of a bare name wins.
    attributed_server: dict[str, str] = {}
    for name in pm.get_server_names():
        config = pm._server_configs.get(name)
        if not config or config.mode != ServerMode.COLD:
            continue
        if not is_discoverable(config):
            continue
        for tool_entry in config.tools_index or []:
            tool_name = tool_entry.get("name")
            if not tool_name or tool_name in attributed_server:
                continue
            attributed_server[tool_name] = name

    listed_names = {t["name"] for t in await _list_tools(pm)}
    dmcp = DynamicMCP()

    for tool_name in listed_names & attributed_server.keys():
        resolved = dmcp.get_server_for_tool_from_index(tool_name, pm)
        expected_server = attributed_server[tool_name]
        assert resolved == expected_server, (
            f"advertised tool '{tool_name}' resolves to server "
            f"'{resolved}' but was advertised under '{expected_server}' "
            f"(collector/resolver disagree — see is_discoverable filter)"
        )
        resolved_config = pm._server_configs.get(resolved)
        assert resolved_config and is_discoverable(resolved_config), (
            f"advertised tool '{tool_name}' resolved to non-discoverable "
            f"server '{resolved}'"
        )


# ── Token budget guard ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tools_list_json_size_stays_within_budget(monkeypatch):
    """Guard against description-bloat regressions. The measured serialized
    size (meta-tools + all discoverable COLD stubs, from the real registry
    mirror) was ~9.0KB at the time this test was written; ceiling is 1.5x
    that measured value to leave headroom for legitimate registry growth
    while still catching a bloat regression."""
    from app.core.mcp_config_loader import load_mcp_config

    parsed = load_mcp_config(str(REPO_ROOT / "mcp-config.json.example"))

    pm = _build_pm(monkeypatch)
    pm._server_configs = dict(parsed)

    tools = await _list_tools(pm)
    size = len(json.dumps(tools))

    # Measured at write time: ~9.0KB serialized (meta-tools + COLD stubs
    # from mcp-config.json.example, no HOT server tools since none are
    # wired to respond in this stub ProcessManager).
    MEASURED_BASELINE = 9010
    ceiling = int(MEASURED_BASELINE * 1.5)
    assert size <= ceiling, (
        f"tools/list serialized size {size} bytes exceeds {ceiling} byte "
        f"budget ({MEASURED_BASELINE} baseline * 1.5) — check for "
        f"description bloat in tools_index or the COLD stub builder"
    )


# ── End-to-end 1-hop proof (reuses auto-discovery machinery) ────────────


@pytest.mark.asyncio
async def test_tools_list_advertised_name_is_directly_callable_one_hop(monkeypatch):
    """A client that ONLY reads tools/list learns the bare tool name from
    this module's stub entry, then calls it directly via tools/call and it
    resolves through DynamicMCP.auto_discover_and_execute with no
    airis-find/airis-exec round trip — proving the advertised name is
    exactly what auto-discovery expects."""
    pm = _build_pm(monkeypatch)
    pm._server_configs["stripe"] = _make_config(
        "stripe",
        enabled=False,
        tools_index=[{"name": "create_customer", "description": "Create a Stripe customer"}],
    )

    # Step 1: client reads tools/list and learns the name.
    tools = {t["name"] for t in await _list_tools(pm)}
    assert "create_customer" in tools

    # Step 2: client calls that exact name directly via tools/call, with no
    # server prefix and no airis-find/airis-exec involved — proving the
    # 1-hop path (mirrors test_cold_tool_auto_discovery.py's
    # test_cold_tool_auto_discovered_and_executed).
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

    result = await dmcp.auto_discover_and_execute("create_customer", {"email": "x@y.com"}, pm)

    assert result == {"result": {"content": [{"type": "text", "text": "ok"}], "isError": False}}
    assert "enable:stripe" in call_log
    assert "call:stripe:create_customer" in call_log
