"""Endpoints for aggregated dashboard data."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.dashboard import DashboardSummaryResponse
from ...services.dashboard_summary import build_dashboard_summary

router = APIRouter(tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    """Return MCP server summary for dashboards / tray apps."""
    return await build_dashboard_summary(db)
