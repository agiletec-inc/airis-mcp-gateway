"""
`api_router` below (dashboard/secrets/mcp-config/server-states/admin — all
DB-backed via SQLAlchemy) is intentionally UNMOUNTED. `app.main` mounts only
`mcp_proxy`, `process_mcp`, and `sse_tools` directly; it never imports this
module's `api_router`.

This is by design, not an oversight (issue #196): SQLAlchemy is a test-extra
dependency (`.[test]`), not a runtime dependency of the production/lite
image, so the shipped container must be able to boot the MCP gateway without
it. Mounting `api_router` requires adding `sqlalchemy` (and its async driver)
to the runtime dependency group first.

Guarded mechanically by `tests/unit/test_lite_mode_invariants.py`:
(a) importing `app.main` never imports `sqlalchemy`, and (b) none of this
router's paths appear in the app's effective route table.
"""

from fastapi import APIRouter
from .endpoints.mcp_servers import router as mcp_servers_router
from .endpoints.secrets import router as secrets_router
from .endpoints.mcp_proxy import router as mcp_proxy_router
from .endpoints.gateway import router as gateway_router
from .endpoints.mcp_server_states import router as mcp_server_states_router
from .endpoints.mcp_config import router as mcp_config_router
from .endpoints.validate_server import router as validate_server_router
from .endpoints.mcp_admin import router as mcp_admin_router
from .endpoints.dashboard import router as dashboard_router

api_router = APIRouter()

api_router.include_router(
    mcp_servers_router, prefix="/mcp/servers", tags=["MCP Servers"]
)

api_router.include_router(secrets_router, prefix="/secrets", tags=["Secrets"])

api_router.include_router(gateway_router, prefix="/gateway", tags=["Gateway Control"])

api_router.include_router(
    mcp_server_states_router, prefix="/server-states", tags=["Server States"]
)

api_router.include_router(
    mcp_config_router, prefix="/mcp-config", tags=["MCP Configuration"]
)

api_router.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])

api_router.include_router(
    validate_server_router, prefix="/validate", tags=["Server Validation"]
)

api_router.include_router(mcp_admin_router, tags=["MCP Admin"])

# MCP Proxy with OpenMCP Schema Partitioning (75-90% token reduction)
api_router.include_router(mcp_proxy_router, prefix="/mcp", tags=["MCP Proxy"])
