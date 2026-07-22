"""Authentication tests for the /process/* admin endpoints (issue #97).

The /process/* router exposes high-impact admin/mutation endpoints
(enable/disable servers, arbitrary tool calls, raw JSON-RPC). These tests
pin the `verify_api_key` dependency contract and prove the dependency is
actually wired onto the router.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from app.api.endpoints import process_mcp
from app.core.auth import verify_api_key
from app.core.config import settings

API_KEY = "test-secret-key-123"


class _FakeRequest:
    """Minimal stand-in exposing only what verify_api_key reads."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


# ── verify_api_key: key configured ───────────────────────────────────────────


def test_rejects_request_without_authorization_header(monkeypatch):
    monkeypatch.setattr(settings, "AIRIS_API_KEY", API_KEY)

    with pytest.raises(HTTPException) as exc:
        verify_api_key(_FakeRequest())

    assert exc.value.status_code == 401


def test_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "AIRIS_API_KEY", API_KEY)

    with pytest.raises(HTTPException) as exc:
        verify_api_key(_FakeRequest({"authorization": "Bearer wrong-token"}))

    assert exc.value.status_code == 401


def test_accepts_correct_token(monkeypatch):
    monkeypatch.setattr(settings, "AIRIS_API_KEY", API_KEY)

    # Returns None (no exception) when the token matches.
    assert verify_api_key(_FakeRequest({"authorization": f"Bearer {API_KEY}"})) is None


def test_accepts_token_with_case_insensitive_scheme(monkeypatch):
    monkeypatch.setattr(settings, "AIRIS_API_KEY", API_KEY)

    assert verify_api_key(_FakeRequest({"authorization": f"bearer {API_KEY}"})) is None


# ── verify_api_key: no key configured ────────────────────────────────────────


def test_open_access_in_development_when_no_key(monkeypatch):
    monkeypatch.setattr(settings, "AIRIS_API_KEY", None)
    monkeypatch.setattr(settings, "ENV", "development")

    # Local-dev convenience: open access, no exception.
    assert verify_api_key(_FakeRequest()) is None


def test_fails_closed_in_production_when_no_key(monkeypatch):
    monkeypatch.setattr(settings, "AIRIS_API_KEY", None)
    monkeypatch.setattr(settings, "ENV", "production")

    with pytest.raises(HTTPException) as exc:
        verify_api_key(_FakeRequest())

    assert exc.value.status_code == 503


def test_fails_closed_in_staging_when_no_key(monkeypatch):
    monkeypatch.setattr(settings, "AIRIS_API_KEY", None)
    monkeypatch.setattr(settings, "ENV", "staging")

    with pytest.raises(HTTPException) as exc:
        verify_api_key(_FakeRequest())

    assert exc.value.status_code == 503


# ── router wiring ────────────────────────────────────────────────────────────


def _client() -> TestClient:
    """Mount the real /process router in isolation (no global middleware)."""
    app = FastAPI()
    app.include_router(process_mcp.router, prefix="/process")
    return TestClient(app, raise_server_exceptions=False)


def test_process_router_requires_auth_when_key_set(monkeypatch):
    """The router-level dependency rejects unauthenticated requests."""
    monkeypatch.setattr(settings, "AIRIS_API_KEY", API_KEY)

    response = _client().get("/process/servers")

    assert response.status_code == 401


def test_process_router_fails_closed_in_staging_without_key(monkeypatch):
    """Without a key, /process/* is disabled outside development."""
    monkeypatch.setattr(settings, "AIRIS_API_KEY", None)
    monkeypatch.setattr(settings, "ENV", "staging")

    response = _client().get("/process/servers")

    assert response.status_code == 503


def test_process_mutation_endpoint_rejects_unauthenticated_caller(monkeypatch):
    """A disable call (DoS vector) is rejected before reaching the handler."""
    monkeypatch.setattr(settings, "AIRIS_API_KEY", API_KEY)

    response = _client().post("/process/servers/context7/disable")

    assert response.status_code == 401
