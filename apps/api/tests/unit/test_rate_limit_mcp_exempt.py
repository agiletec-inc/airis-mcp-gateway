"""Tests for MCP Streamable HTTP transport GET/HEAD rate-limit exemption."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware.rate_limit import RateLimitMiddleware, RateLimitStore


async def _ok(request):
    return PlainTextResponse("ok")


def _build_client() -> TestClient:
    """Build a minimal Starlette app with the rate-limit middleware wired up.

    Uses a fresh RateLimitStore per test to avoid cross-test pollution of the
    global store.
    """
    app = Starlette(
        routes=[
            Route("/mcp", _ok, methods=["GET", "HEAD"]),
            Route("/mcp/", _ok, methods=["GET", "HEAD"]),
            Route("/mcp/sse", _ok, methods=["GET", "HEAD"]),
            Route("/sse", _ok, methods=["GET", "HEAD"]),
            Route("/api/v1/data", _ok, methods=["POST"]),
        ]
    )
    store = RateLimitStore()
    app.add_middleware(RateLimitMiddleware, store=store)
    return TestClient(app)


def test_get_mcp_beyond_limit_is_exempt():
    client = _build_client()

    # Fire far more GET requests than the default per-IP limit (100/min).
    for _ in range(150):
        response = client.get("/mcp")
        assert response.status_code == 200

    # Trailing-slash variant is exempt too.
    for _ in range(50):
        response = client.get("/mcp/")
        assert response.status_code == 200


def test_head_mcp_beyond_limit_is_exempt():
    client = _build_client()

    for _ in range(150):
        response = client.head("/mcp")
        assert response.status_code == 200


def test_get_mcp_sse_stream_beyond_limit_is_exempt():
    """Regression test for #211: the Streamable HTTP resumable GET stream at
    `/mcp/sse` — the long-lived route the exemption comment actually
    describes — was missing from MCP_TRANSPORT_READ_PATHS, so a reconnect
    storm on this exact path could still 429-lock out every local client."""
    client = _build_client()

    for _ in range(150):
        response = client.get("/mcp/sse")
        assert response.status_code == 200


def test_get_classic_sse_beyond_limit_is_exempt():
    """Regression test for #211: the classic SSE transport at `/sse`
    (Gemini CLI / Cursor / Windsurf per this repo's CLAUDE.md) was also
    missing from the exemption."""
    client = _build_client()

    for _ in range(150):
        response = client.get("/sse")
        assert response.status_code == 200


def test_post_still_rate_limited_after_exceeding_limit():
    app = Starlette(
        routes=[
            Route("/api/v1/data", _ok, methods=["POST"]),
        ]
    )
    store = RateLimitStore()
    app.add_middleware(RateLimitMiddleware, store=store)
    client = TestClient(app)

    # Pre-fill the store so the very next POST from this client IP exceeds
    # the per-IP limit, without needing to send hundreds of real requests.
    from app.middleware.rate_limit import RATE_LIMIT_PER_IP

    key = "ip:testclient"
    store.check_and_increment(key, RATE_LIMIT_PER_IP)
    store._store[key].count = RATE_LIMIT_PER_IP

    response = client.post("/api/v1/data")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
