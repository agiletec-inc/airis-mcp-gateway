from app.main import app
from test_mcp_route_presence import iter_effective_routes


def test_public_sse_route_registered():
    """Verify the Codex-compatible /sse passthrough stays wired up."""
    matching_routes = [
        (path, methods) for path, methods, _route in iter_effective_routes(app)
        if path == "/sse"
    ]
    assert matching_routes, "Expected /sse route to be registered on the FastAPI app"
    assert any("GET" in (methods or set()) for _path, methods in matching_routes)


def test_public_mcp_root_routes_registered():
    """Ensure /mcp root aliases exist for HTTP MCP transports."""
    matching_routes = [
        (path, methods) for path, methods, _route in iter_effective_routes(app)
        if path in {"/mcp", "/mcp/"}
    ]
    assert matching_routes, "Expected /mcp routes to be registered on the FastAPI app"
    for _path, methods in matching_routes:
        assert methods, "Route should advertise supported HTTP methods"
    assert any("DELETE" in (methods or set()) for _path, methods in matching_routes)


def test_public_well_known_route_registered():
    """Ensure Streamable HTTP discovery is exposed at the application root."""
    matching_routes = [
        (path, methods) for path, methods, _route in iter_effective_routes(app)
        if path == "/.well-known/{path:path}"
    ]
    assert matching_routes, "Expected root /.well-known proxy route to be registered"
    assert any("GET" in (methods or set()) for _path, methods in matching_routes)
