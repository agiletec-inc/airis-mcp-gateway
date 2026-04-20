"""
Regression test for Lazy Schema applied to HOT server tools.

In DYNAMIC_MCP mode, apply_schema_partitioning() must strip every HOT
server tool's inputSchema down to `{"type": "object"}` when
`settings.SCHEMA_MODE == "lazy"`. The full schema is expected to stay
available via the DynamicMCP cache / schema_partitioner so that
airis-schema and the /tools/call error-injection path can retrieve it
on demand.

This test runs the real apply_schema_partitioning with a stubbed
ProcessManager so we exercise the actual transformation, not a mock.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.endpoints import tool_shaping
from app.core.config import settings


@pytest.mark.asyncio
async def test_hot_tools_get_lazy_stub_in_dynamic_mcp_lazy_mode(monkeypatch):
    # A synthetic HOT server whose tool carries a richly-typed schema.
    def fake_hot_servers():
        return ["stripe"]

    async def fake_list_tools(server_name=None, mode=None):
        assert server_name == "stripe"
        return [
            {
                "name": "stripe_create_customer",
                "description": "Create a Stripe customer",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "required": ["email"],
                },
            }
        ]

    pm = MagicMock()
    pm.get_hot_servers = fake_hot_servers
    pm.list_tools = AsyncMock(side_effect=fake_list_tools)

    monkeypatch.setattr(tool_shaping, "get_process_manager", lambda: pm)
    monkeypatch.setattr(settings, "DYNAMIC_MCP", True)
    monkeypatch.setattr(settings, "SCHEMA_MODE", "lazy")

    data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    out = await tool_shaping.apply_schema_partitioning(data)
    tools = {t["name"]: t for t in out["result"]["tools"]}

    assert "stripe_create_customer" in tools, tools.keys()
    assert tools["stripe_create_customer"]["inputSchema"] == {"type": "object"}, (
        "HOT tool inputSchema must be stubbed to {'type':'object'} in lazy mode"
    )


@pytest.mark.asyncio
async def test_hot_tools_keep_full_schema_in_full_mode(monkeypatch):
    """SCHEMA_MODE=full must preserve the backend's original inputSchema."""
    pm = MagicMock()
    pm.get_hot_servers = lambda: ["stripe"]
    pm.list_tools = AsyncMock(return_value=[
        {
            "name": "stripe_create_customer",
            "description": "Create a Stripe customer",
            "inputSchema": {
                "type": "object",
                "properties": {"email": {"type": "string"}},
                "required": ["email"],
            },
        }
    ])

    monkeypatch.setattr(tool_shaping, "get_process_manager", lambda: pm)
    monkeypatch.setattr(settings, "DYNAMIC_MCP", True)
    monkeypatch.setattr(settings, "SCHEMA_MODE", "full")

    data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    out = await tool_shaping.apply_schema_partitioning(data)
    tools = {t["name"]: t for t in out["result"]["tools"]}

    schema = tools["stripe_create_customer"]["inputSchema"]
    assert "properties" in schema, "full mode must retain the original inputSchema"
    assert schema["required"] == ["email"]
