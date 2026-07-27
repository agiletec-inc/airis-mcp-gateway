"""Administrative endpoints for MCP credential and toggle management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ...dependencies import AdminContext, get_admin_context
from ...schemas.mcp_admin import (
    ConnectorStatus,
    CredentialResponse,
    CredentialSave,
    EnableRequest,
    EnableResponse,
    ProbeResponse,
)

router = APIRouter(prefix="/admin/mcp", tags=["admin.mcp"])


@router.get(
    "/",
    response_model=list[ConnectorStatus],
    summary="List connector status",
)
async def list_connectors(ctx: AdminContext = Depends(get_admin_context)):
    settings = await ctx.settings_repo.list()
    results: list[ConnectorStatus] = []
    for entry in settings:
        results.append(
            ConnectorStatus(
                id=entry.id,
                enabled=entry.enabled,
                updated_at=entry.updated_at,
            )
        )
    return results


@router.patch(
    "/{connector_id}/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_200_OK,
    summary="Store / rotate connector credential",
)
async def save_credentials(
    connector_id: str,
    payload: CredentialSave,
    ctx: AdminContext = Depends(get_admin_context),
):
    provider = payload.provider or connector_id
    try:
        result = await ctx.credential_provider.set(
            connector_id,
            provider,
            payload.api_key,
            ctx.actor,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return CredentialResponse(
        id=result["id"],
        provider=result["provider"],
        version=result["version"],
        updated_at=result.get("updated_at"),
    )


@router.post(
    "/{connector_id}/test",
    response_model=ProbeResponse,
    summary="Perform credential probe",
)
async def test_connector(
    connector_id: str,
    ctx: AdminContext = Depends(get_admin_context),
):
    ok = await ctx.registry.probe(connector_id)
    return ProbeResponse(ok=ok)


@router.post(
    "/{connector_id}/enable",
    response_model=EnableResponse,
    summary="Enable or disable connector",
)
async def toggle_connector(
    connector_id: str,
    payload: EnableRequest,
    ctx: AdminContext = Depends(get_admin_context),
):
    if payload.enabled:
        ok = await ctx.registry.probe(connector_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AUTH_FAILED_OR_UNREACHABLE",
            )
        setting = await ctx.settings_repo.enable(connector_id)
        enabled = setting.enabled
    else:
        setting = await ctx.settings_repo.disable(connector_id)
        enabled = setting.enabled

    return EnableResponse(ok=True, enabled=enabled)
