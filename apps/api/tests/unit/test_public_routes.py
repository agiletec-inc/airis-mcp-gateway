from app.main import app


def test_public_sse_route_registered():
    """Verify the Codex-compatible /sse passthrough stays wired up."""
    matching_routes = [
        route for route in app.routes if getattr(route, "path", None) == "/sse"
    ]
    assert matching_routes, "Expected /sse route to be registered on the FastAPI app"
    assert any("GET" in getattr(route, "methods", set()) for route in matching_routes)


def test_public_mcp_root_routes_registered():
    """Ensure /mcp root aliases exist for HTTP MCP transports."""
    matching_routes = [
        route for route in app.routes if getattr(route, "path", None) in {"/mcp", "/mcp/"}
    ]
    assert matching_routes, "Expected /mcp routes to be registered on the FastAPI app"
    for route in matching_routes:
        methods = getattr(route, "methods", set())
        assert methods, "Route should advertise supported HTTP methods"
    assert any("DELETE" in getattr(route, "methods", set()) for route in matching_routes)


def test_public_well_known_route_registered():
    """Ensure Streamable HTTP discovery is exposed at the application root."""
    matching_routes = [
        route for route in app.routes
        if getattr(route, "path", None) == "/.well-known/{path:path}"
    ]
    assert matching_routes, "Expected root /.well-known proxy route to be registered"
    assert any("GET" in getattr(route, "methods", set()) for route in matching_routes)
