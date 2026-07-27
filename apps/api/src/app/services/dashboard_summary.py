"""Dashboard summary aggregation logic."""

from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.endpoints.mcp_config import load_mcp_servers_from_config
from ..crud import secret as secret_crud
from ..crud import mcp_server_state as state_crud
from ..schemas.dashboard import (
    DashboardStats,
    DashboardSummaryResponse,
    ServerSummary,
)


from typing import Literal

ServerStatus = Literal["connected", "disconnected", "error"]


def _default_status(enabled: bool) -> ServerStatus:
    return "connected" if enabled else "disconnected"


async def build_dashboard_summary(db: AsyncSession) -> DashboardSummaryResponse:
    """Compose a single payload describing all MCP servers and quick stats."""
    server_configs = load_mcp_servers_from_config()
    secrets = await secret_crud.get_all_secrets(db)
    states = await state_crud.get_all_server_states(db)

    secrets_by_server = defaultdict(list)
    for secret in secrets:
        secrets_by_server[secret.server_name].append(secret)

    states_by_server = {state.server_id: state.enabled for state in states}

    summaries: list[ServerSummary] = []
    api_key_missing = 0
    active = 0

    for server in server_configs:
        enabled = states_by_server.get(server.id, False)
        if enabled:
            active += 1

        api_key_configured = server.id in secrets_by_server
        if server.apiKeyRequired and not api_key_configured:
            api_key_missing += 1

        summaries.append(
            ServerSummary(
                id=server.id,
                name=server.name,
                description=server.description,
                category=server.category,
                enabled=enabled,
                status=_default_status(enabled),
                api_key_required=server.apiKeyRequired,
                api_key_configured=api_key_configured,
                recommended=server.recommended,
                builtin=server.builtin,
                tool_count=None,
                tools=[],
            )
        )

    stats = DashboardStats(
        total=len(summaries),
        active=active,
        inactive=len(summaries) - active,
        api_key_missing=api_key_missing,
    )

    return DashboardSummaryResponse(stats=stats, servers=summaries)
