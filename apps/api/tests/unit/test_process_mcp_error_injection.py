"""
Regression test for the -32602 error-injection path in process_mcp /tools/call.

The endpoint wraps `ProcessManager.call_tool()` and, when the backend server
returns `-32602 Invalid params` (or `-32000`), re-hydrates the error payload
with the tool's full input schema so the caller can self-heal on the next
attempt without a separate airis-schema round-trip.

An earlier edit referenced `manager._tools`, which does not exist on
ProcessManager (the tool cache lives on DynamicMCP), so the injection path
raised AttributeError at runtime. This test pins the working contract.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import process_mcp
from app.core.dynamic_mcp import DynamicMCP, ToolInfo
from app.core.process_manager import ProcessManager


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient wired to stubbed ProcessManager + DynamicMCP singletons."""
    pm = ProcessManager()
    pm._initialized = True
    monkeypatch.setattr("app.api.endpoints.process_mcp.get_process_manager", lambda: pm)

    dmcp = DynamicMCP()
    dmcp._tools["stripe_create_customer"] = ToolInfo(
        name="stripe_create_customer",
        server="stripe",
        description="Create a Stripe customer",
        input_schema={
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "required": ["email"],
        },
        source="process",
    )
    monkeypatch.setattr("app.core.dynamic_mcp.get_dynamic_mcp", lambda: dmcp)

    app = FastAPI()
    app.include_router(process_mcp.router)
    return TestClient(app), pm


def test_invalid_params_error_gets_schema_injected(client, monkeypatch):
    tc, pm = client

    async def fake_call_tool(name, arguments):
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32602, "message": "Invalid params"},
        }

    monkeypatch.setattr(pm, "call_tool", fake_call_tool)

    resp = tc.post(
        "/tools/call",
        json={"name": "stripe_create_customer", "arguments": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"]["code"] == -32602
    assert "Full Schema" in body["error"]["message"]
    assert "email" in body["error"]["message"]
    assert body["error"]["hint"].startswith("Retry")


def test_non_validation_errors_pass_through_untouched(client, monkeypatch):
    tc, pm = client

    async def fake_call_tool(name, arguments):
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }

    monkeypatch.setattr(pm, "call_tool", fake_call_tool)

    resp = tc.post(
        "/tools/call",
        json={"name": "stripe_create_customer", "arguments": {}},
    )
    body = resp.json()
    assert body["error"]["code"] == -32601
    assert "Full Schema" not in body["error"]["message"]
    assert "hint" not in body["error"]


def test_unknown_tool_does_not_raise(client, monkeypatch):
    """If the tool isn't in the DynamicMCP cache, injection is silently skipped."""
    tc, pm = client

    async def fake_call_tool(name, arguments):
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32602, "message": "Invalid params"},
        }

    monkeypatch.setattr(pm, "call_tool", fake_call_tool)

    resp = tc.post(
        "/tools/call",
        json={"name": "unknown_tool", "arguments": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"]["code"] == -32602
    assert "Full Schema" not in body["error"]["message"]
