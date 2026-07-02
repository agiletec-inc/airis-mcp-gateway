"""
Route-presence canary for the Streamable HTTP / SSE transports.

FastAPI 0.137 refactored `include_router()` to preserve `APIRouter` /
`APIRoute` instances instead of cloning them into a flat list: `app.routes`
now contains opaque `_IncludedRouter` tree nodes for any router mounted with
`app.include_router(...)`, so naive top-level path checks on `app.routes`
silently stop finding routes like "/mcp" that live inside a prefixed router
even though the routes still dispatch correctly at runtime (see issue #191).

This test walks the *effective* route table — recursing into both the old
(flat, pre-0.137) and new (tree, 0.137+) shapes — so it fails loudly if a
future FastAPI/Starlette change (or a refactor of our own routers) drops a
route that a live transport depends on, instead of passing on structure that
no longer reflects what actually gets served.
"""
from app.main import app


def iter_effective_routes(router_or_app, prefix=""):
    """Yield (full_path, methods, route) for every dispatchable route.

    Recurses into FastAPI 0.137+ `_IncludedRouter` nodes (via
    `original_router` + `include_context.prefix`) and into any other
    Mount-like object exposing nested `.routes`. On FastAPI <0.137,
    `app.routes` is already flat with the prefix baked into `route.path`,
    so the recursion below is a no-op for those routes.
    """
    routes = getattr(router_or_app, "routes", None)
    if not routes:
        return

    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            include_context = getattr(route, "include_context", None)
            sub_prefix = getattr(include_context, "prefix", "") or ""
            yield from iter_effective_routes(original_router, prefix + sub_prefix)
            continue

        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path, getattr(route, "methods", None), route
            continue

        # Generic Mount-like node with nested routes but no direct path.
        if getattr(route, "routes", None):
            yield from iter_effective_routes(route, prefix)


def _methods_for(effective_routes, path):
    methods = set()
    for full_path, route_methods, _route in effective_routes:
        if full_path == path and route_methods:
            methods |= set(route_methods)
    return methods


def test_mcp_root_routes_dispatch_get_post_delete():
    """The Streamable HTTP transport root must keep GET/POST/DELETE."""
    effective_routes = list(iter_effective_routes(app))

    mcp_paths_seen = {
        full_path for full_path, _methods, _route in effective_routes
        if full_path in {"/mcp", "/mcp/"}
    }
    assert mcp_paths_seen, "Expected /mcp or /mcp/ to be registered on the FastAPI app"

    combined_methods = set()
    for path in ("/mcp", "/mcp/"):
        combined_methods |= _methods_for(effective_routes, path)

    for required_method in ("GET", "POST", "DELETE"):
        assert required_method in combined_methods, (
            f"Expected {required_method} to route to /mcp or /mcp/, "
            f"got methods={combined_methods}"
        )


def test_sse_routes_dispatch_get_post():
    """The classic SSE transport must keep GET/POST at /sse."""
    effective_routes = list(iter_effective_routes(app))

    sse_methods = _methods_for(effective_routes, "/sse")
    assert sse_methods, "Expected /sse to be registered on the FastAPI app"

    for required_method in ("GET", "POST"):
        assert required_method in sse_methods, (
            f"Expected {required_method} to route to /sse, got methods={sse_methods}"
        )
