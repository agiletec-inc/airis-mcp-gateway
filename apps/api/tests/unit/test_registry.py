"""Tests for MCPRegistry (issue #85)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.registry import MCPRegistry


class _FakeCredentials:
    """Minimal CredentialProvider stand-in."""

    def __init__(self):
        self._subscribers: list = []

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def notify(self, connector_id: str, ts: int = 0):
        for cb in list(self._subscribers):
            cb(connector_id, ts)


class _FakeClient:
    """Minimal connector client stand-in."""

    def __init__(self, name: str):
        self.name = name
        self.reset_auth = MagicMock()
        self.light_probe = AsyncMock()
        self.invoke = AsyncMock(return_value={"value": 42})


@pytest.fixture
def registry_with_stub(monkeypatch):
    creds = _FakeCredentials()
    clients: dict[str, _FakeClient] = {}

    def _build(connector_id: str, _creds):
        clients[connector_id] = _FakeClient(connector_id)
        return clients[connector_id]

    monkeypatch.setattr(
        "app.core.registry.build_connector",
        _build,
    )

    registry = MCPRegistry(creds)
    return registry, clients, creds


@pytest.mark.asyncio
async def test_invoke_returns_ok_on_success(registry_with_stub):
    registry, clients, _ = registry_with_stub

    result = await registry.invoke("stripe", "create", {"amount": 100})

    assert result == {"ok": True, "data": {"value": 42}}
    clients["stripe"].invoke.assert_awaited_once_with("create", {"amount": 100})


@pytest.mark.asyncio
async def test_invoke_records_failure_on_exception(registry_with_stub):
    registry, clients, _ = registry_with_stub
    clients_will_register = MCPRegistry  # noqa: F841 — ensure import still works
    # Eagerly materialise the client so we can override its behaviour.
    await registry._get("stripe")
    clients["stripe"].invoke.side_effect = RuntimeError("boom")

    result = await registry.invoke("stripe", "create", {})

    assert result["ok"] is False
    assert "boom" in result["error"]


@pytest.mark.asyncio
async def test_invoke_short_circuits_when_circuit_open(registry_with_stub):
    registry, clients, _ = registry_with_stub
    await registry._get("stripe")

    # Force the circuit open.
    registry._circuits["stripe"].record_failure()

    result = await registry.invoke("stripe", "create", {})

    assert result["ok"] is False
    assert result["error"] == "CIRCUIT_OPEN"
    assert "retryAt" in result
    clients["stripe"].invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_probe_records_success(registry_with_stub):
    registry, clients, _ = registry_with_stub

    assert await registry.probe("stripe") is True

    clients["stripe"].light_probe.assert_awaited_once()
    assert registry._circuits["stripe"].allow() is True


@pytest.mark.asyncio
async def test_probe_records_failure(registry_with_stub):
    registry, clients, _ = registry_with_stub
    await registry._get("stripe")
    clients["stripe"].light_probe.side_effect = RuntimeError("unreachable")

    assert await registry.probe("stripe") is False
    # After a failure the circuit should be OPEN until the backoff elapses.
    assert registry._circuits["stripe"].state.state == "OPEN"


@pytest.mark.asyncio
async def test_get_reuses_existing_client(registry_with_stub):
    registry, clients, _ = registry_with_stub

    client1, circuit1 = await registry._get("stripe")
    client2, circuit2 = await registry._get("stripe")

    assert client1 is client2
    assert circuit1 is circuit2
    assert len(clients) == 1


@pytest.mark.asyncio
async def test_credential_change_triggers_reset_and_half_open(registry_with_stub):
    registry, clients, creds = registry_with_stub
    await registry._get("stripe")
    registry._circuits["stripe"].record_failure()  # OPEN

    creds.notify("stripe", ts=123)

    clients["stripe"].reset_auth.assert_called_once()
    assert registry._circuits["stripe"].state.state == "HALF_OPEN"


@pytest.mark.asyncio
async def test_credential_change_without_existing_client_is_noop(registry_with_stub):
    registry, _clients, creds = registry_with_stub

    # Should not raise even though nothing has been materialised yet.
    creds.notify("unknown-server")
