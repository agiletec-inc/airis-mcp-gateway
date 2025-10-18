from fastapi import APIRouter
from .endpoints import mcp_servers_router
from .endpoints.secrets import router as secrets_router
from .endpoints.mcp_proxy import router as mcp_proxy_router
from .endpoints.gateway import router as gateway_router
from .endpoints.mcp_server_states import router as mcp_server_states_router
from .endpoints.mcp_config import router as mcp_config_router

api_router = APIRouter()

api_router.include_router(
    mcp_servers_router,
    prefix="/mcp/servers",
    tags=["MCP Servers"]
)

api_router.include_router(
    secrets_router,
    prefix="/secrets",
    tags=["Secrets"]
)

api_router.include_router(
    gateway_router,
    prefix="/gateway",
    tags=["Gateway Control"]
)

api_router.include_router(
    mcp_server_states_router,
    prefix="/server-states",
    tags=["Server States"]
)

api_router.include_router(
    mcp_config_router,
    prefix="/mcp-config",
    tags=["MCP Configuration"]
)

# MCP Proxy with OpenMCP Schema Partitioning (75-90% token reduction)
api_router.include_router(
    mcp_proxy_router,
    prefix="/mcp",
    tags=["MCP Proxy"]
)
