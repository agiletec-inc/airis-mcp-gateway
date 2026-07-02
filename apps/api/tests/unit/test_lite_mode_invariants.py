"""
Lite-mode invariant gate (issue #196).

`app/api/routes.py::api_router` bundles the DB-backed endpoints (dashboard,
secrets, mcp-config, server-states, mcp-admin — all transitively import
SQLAlchemy via `app.dependencies` / `app.core.database`). It is intentionally
never mounted on `app.main.app`: SQLAlchemy is a test-extra dependency, not a
runtime dependency of the production/lite image, so the shipped gateway must
be able to boot without it.

This test makes that invariant mechanical instead of tribal knowledge:

(a) A fresh `import app.main` — in a clean subprocess, so this test's own
    process (whose `tests/unit/conftest.py` already imports SQLAlchemy for
    the DB-backed test fixtures) cannot contaminate the result — must never
    pull in `sqlalchemy`.
(b) None of `api_router`'s mounted paths are reachable on the live app's
    effective route table (reusing the FastAPI-0.137-safe route walker from
    `test_mcp_route_presence.py`).
"""
import subprocess
import sys

from test_mcp_route_presence import iter_effective_routes

from app.api import routes as routes_module
from app.main import app

# One representative prefix per router mounted on api_router (see routes.py).
# If api_router ever gets mounted on app.main.app, any of these paths
# resolving would catch it.
API_ROUTER_PREFIXES = (
    "/mcp/servers",
    "/secrets",
    "/gateway",
    "/server-states",
    "/mcp-config",
    "/dashboard",
    "/validate",
)


def test_fresh_app_import_does_not_pull_in_sqlalchemy():
    """`app.main` must be importable without SQLAlchemy ever landing in
    sys.modules — that is what makes the lite/production image viable
    without the `sqlalchemy` runtime dependency.

    Run in a subprocess: this test file's own session has already imported
    SQLAlchemy (tests/unit/conftest.py does, for the DB-fixture tests), so
    checking sys.modules in-process would always pass trivially.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.main; "
            "assert 'sqlalchemy' not in sys.modules, "
            "'app.main import pulled in sqlalchemy: ' + str([m for m in sys.modules if 'sqlalchemy' in m])",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Fresh `import app.main` failed or imported sqlalchemy.\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_db_backed_api_router_is_not_mounted_on_app():
    """`routes.api_router`'s paths must not be reachable on the live app —
    it is unmounted by design (see the module docstring in routes.py)."""
    # Sanity check: api_router really does declare these DB-backed routes,
    # so this test would fail loudly (not vacuously pass) if routes.py's
    # router wiring changed shape. Uses the same tree-walker as the live-app
    # check below, since FastAPI 0.137+ nests included sub-routers instead
    # of flattening them onto `api_router.routes` (see test_mcp_route_presence.py).
    declared_paths = {
        full_path for full_path, _methods, _route in iter_effective_routes(routes_module.api_router)
    }
    assert declared_paths, "api_router declared no routes — sanity check failed"

    effective_paths = {
        full_path for full_path, _methods, _route in iter_effective_routes(app)
    }

    for prefix in API_ROUTER_PREFIXES:
        mounted = [p for p in effective_paths if p.startswith(prefix)]
        assert not mounted, (
            f"api_router path prefix {prefix!r} is reachable on the live app "
            f"({mounted}) — it must stay unmounted (lite mode, issue #196)"
        )
