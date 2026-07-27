"""Schemas for dashboard summary and server status."""

from pydantic import BaseModel
from typing import Literal


class ToolSummary(BaseModel):
    """Basic information about MCP tools exposed by a server."""

    id: str
    name: str | None = None
    description: str | None = None


class ServerSummary(BaseModel):
    """Aggregated view of a single MCP server."""

    id: str
    name: str
    description: str
    category: str
    enabled: bool
    status: Literal["connected", "disconnected", "error"]
    api_key_required: bool
    api_key_configured: bool
    recommended: bool
    builtin: bool
    tool_count: int | None = None
    tools: list[ToolSummary] = []


class DashboardStats(BaseModel):
    """Top-level counts for quick glancing in UI / menu bar."""

    total: int
    active: int
    inactive: int
    api_key_missing: int


class DashboardSummaryResponse(BaseModel):
    """Full response for dashboard summary endpoint."""

    stats: DashboardStats
    servers: list[ServerSummary]
