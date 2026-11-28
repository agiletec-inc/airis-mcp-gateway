from types import SimpleNamespace

import httpx
import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.endpoints import mcp_proxy
from app.main import app
from test_mcp_route_presence import iter_effective_routes


def test_public_sse_route_registered():
    """Verify the Codex-compatible /sse passthrough stays wired up."""
    matching_routes = [
        (path, methods)
        for path, methods, _route in iter_effective_routes(app)
        if path == "/sse"
    ]
    assert matching_routes, "Expected /sse route to be registered on the FastAPI app"
    assert any("GET" in (methods or set()) for _path, methods in matching_routes)


def test_public_mcp_root_routes_registered():
    """Ensure /mcp root aliases exist for HTTP MCP transports."""
    matching_routes = [
        (path, methods)
        for path, methods, _route in iter_effective_routes(app)
        if path in {"/mcp", "/mcp/"}
    ]
    assert matching_routes, "Expected /mcp routes to be registered on the FastAPI app"
    for _path, methods in matching_routes:
        assert methods, "Route should advertise supported HTTP methods"
    assert any("DELETE" in (methods or set()) for _path, methods in matching_routes)


def test_public_well_known_route_registered():
    """Ensure Streamable HTTP discovery is exposed at the application root."""
    matching_routes = [
        (path, methods)
        for path, methods, _route in iter_effective_routes(app)
        if path == "/.well-known/{path:path}"
    ]
    assert matching_routes, "Expected root /.well-known proxy route to be registered"
    assert any("GET" in (methods or set()) for _path, methods in matching_routes)


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_public_discovery_preserves_upstream_response(monkeypatch, method):
    body = b": native event\r\nevent: message\r\ndata: opaque\r\n\r\n"

    class DiscoveryStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            if method == "HEAD":
                pytest.fail("HEAD should close the upstream without reading its body")
            yield body

        async def aclose(self):
            self.closed = True

    stream = DiscoveryStream()

    def upstream(request):
        assert request.method == method
        assert str(request.url) == (
            "http://gateway.test/mcp/.well-known/oauth-protected-resource?resource=mcp"
        )
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/event-stream",
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
            stream=stream,
        )

    monkeypatch.setattr(
        mcp_proxy,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: httpx.AsyncClient(
                transport=httpx.MockTransport(upstream), **kwargs
            )
        ),
    )
    monkeypatch.setattr(
        mcp_proxy.settings, "MCP_STREAM_GATEWAY_URL", "http://gateway.test/mcp"
    )

    response = TestClient(app).request(
        method,
        "/.well-known/oauth-protected-resource?resource=mcp",
        headers={"Authorization": "Bearer synthetic-token"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/event-stream"
    assert response.headers["Content-Length"] == str(len(body))
    assert response.headers["Cache-Control"] == "no-store"
    assert response.content == (body if method == "GET" else b"")
    assert stream.closed


@pytest.mark.parametrize("path", ["/sse", "/mcp/sse"])
def test_sse_aliases_keep_stream_and_jsonrpc_dispatch(monkeypatch, path):
    async def stream(request):
        yield b"event: ping\ndata: {}\n\n"

    async def jsonrpc(request):
        return JSONResponse(await request.json(), status_code=202)

    monkeypatch.setattr(mcp_proxy, "proxy_sse_stream", stream)
    monkeypatch.setattr(mcp_proxy, "_proxy_jsonrpc_request", jsonrpc)
    client = TestClient(app)

    for method in ("GET", "POST"):
        response = client.request(method, path, headers={"Accept": "text/event-stream"})
        assert response.status_code == 200
        assert response.headers["X-Accel-Buffering"] == "no"
        assert response.content == b"event: ping\ndata: {}\n\n"

    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    response = client.post(
        f"{path}?sessionid=synthetic",
        headers={"Accept": "text/event-stream"},
        json=request,
    )
    assert response.status_code == 202
    assert response.json() == request
