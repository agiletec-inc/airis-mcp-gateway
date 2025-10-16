"""API endpoints for secret management"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from ...core.database import get_db
from ...schemas import secret as schemas
from ...crud import secret as crud
from ...core.encryption import encryption_manager

router = APIRouter(tags=["secrets"])


@router.post(
    "/",
    response_model=schemas.SecretResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_secret(
    secret_data: schemas.SecretCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new encrypted secret"""
    # Check if secret already exists
    existing = await crud.get_secret(db, secret_data.server_name, secret_data.key_name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Secret '{secret_data.key_name}' for server '{secret_data.server_name}' already exists"
        )

    secret = await crud.create_secret(
        db,
        secret_data.server_name,
        secret_data.key_name,
        secret_data.value
    )
    return secret


@router.get(
    "/",
    response_model=schemas.SecretListResponse
)
async def list_secrets(db: AsyncSession = Depends(get_db)):
    """List all secrets (without values)"""
    secrets = await crud.get_all_secrets(db)
    return {
        "secrets": secrets,
        "total": len(secrets)
    }


@router.get(
    "/{server_name}",
    response_model=list[schemas.SecretResponse]
)
async def get_secrets_by_server(
    server_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Get all secrets for a specific server (without values)"""
    secrets = await crud.get_secrets_by_server(db, server_name)
    return secrets


@router.get(
    "/{server_name}/{key_name}",
    response_model=schemas.SecretWithValue
)
async def get_secret(
    server_name: str,
    key_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific secret with decrypted value"""
    secret = await crud.get_secret(db, server_name, key_name)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret '{key_name}' for server '{server_name}' not found"
        )

    # Decrypt value
    decrypted_value = encryption_manager.decrypt(secret.encrypted_value)

    return {
        **secret.__dict__,
        "value": decrypted_value
    }


@router.put(
    "/{server_name}/{key_name}",
    response_model=schemas.SecretResponse
)
async def update_secret(
    server_name: str,
    key_name: str,
    secret_data: schemas.SecretUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a secret value"""
    secret = await crud.update_secret(db, server_name, key_name, secret_data.value)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret '{key_name}' for server '{server_name}' not found"
        )
    return secret


@router.delete(
    "/{server_name}/{key_name}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_secret(
    server_name: str,
    key_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete a secret"""
    deleted = await crud.delete_secret(db, server_name, key_name)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret '{key_name}' for server '{server_name}' not found"
        )


@router.delete(
    "/{server_name}",
    response_model=dict
)
async def delete_secrets_by_server(
    server_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete all secrets for a server"""
    count = await crud.delete_secrets_by_server(db, server_name)
    return {
        "deleted": count,
        "server_name": server_name
    }
