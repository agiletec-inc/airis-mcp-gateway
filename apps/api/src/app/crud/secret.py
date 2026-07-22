"""CRUD operations for secrets"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.secret import Secret
from ..core.encryption import encryption_manager


async def create_secret(
    db: AsyncSession, server_name: str, key_name: str, value: str
) -> Secret:
    """
    Create a new encrypted secret

    Args:
        db: Database session
        server_name: MCP server name
        key_name: Secret key name
        value: Plaintext secret value

    Returns:
        Created secret
    """
    encrypted_value = encryption_manager.encrypt(value)
    secret = Secret(
        server_name=server_name, key_name=key_name, encrypted_value=encrypted_value
    )
    db.add(secret)
    await db.commit()
    await db.refresh(secret)
    return secret


async def get_secret(
    db: AsyncSession, server_name: str, key_name: str
) -> Secret | None:
    """
    Get a secret by server and key name

    Args:
        db: Database session
        server_name: MCP server name
        key_name: Secret key name

    Returns:
        Secret if found, None otherwise
    """
    result = await db.execute(
        select(Secret).where(
            Secret.server_name == server_name, Secret.key_name == key_name
        )
    )
    return result.scalar_one_or_none()


async def get_secret_value(
    db: AsyncSession, server_name: str, key_name: str
) -> str | None:
    """
    Get decrypted secret value

    Args:
        db: Database session
        server_name: MCP server name
        key_name: Secret key name

    Returns:
        Decrypted value if found, None otherwise
    """
    secret = await get_secret(db, server_name, key_name)
    if secret:
        return encryption_manager.decrypt(secret.encrypted_value)
    return None


async def get_secrets_by_server(db: AsyncSession, server_name: str) -> list[Secret]:
    """
    Get all secrets for a server

    Args:
        db: Database session
        server_name: MCP server name

    Returns:
        List of secrets
    """
    result = await db.execute(select(Secret).where(Secret.server_name == server_name))
    return list(result.scalars().all())


async def get_all_secrets(db: AsyncSession) -> list[Secret]:
    """
    Get all secrets

    Args:
        db: Database session

    Returns:
        List of all secrets
    """
    result = await db.execute(select(Secret))
    return list(result.scalars().all())


async def update_secret(
    db: AsyncSession, server_name: str, key_name: str, value: str
) -> Secret | None:
    """
    Update a secret value

    Args:
        db: Database session
        server_name: MCP server name
        key_name: Secret key name
        value: New plaintext value

    Returns:
        Updated secret if found, None otherwise
    """
    secret = await get_secret(db, server_name, key_name)
    if secret:
        secret.encrypted_value = encryption_manager.encrypt(value)
        await db.commit()
        await db.refresh(secret)
    return secret


async def delete_secret(db: AsyncSession, server_name: str, key_name: str) -> bool:
    """
    Delete a secret

    Args:
        db: Database session
        server_name: MCP server name
        key_name: Secret key name

    Returns:
        True if deleted, False if not found
    """
    secret = await get_secret(db, server_name, key_name)
    if secret:
        await db.delete(secret)
        await db.commit()
        return True
    return False


async def delete_secrets_by_server(db: AsyncSession, server_name: str) -> int:
    """
    Delete all secrets for a server

    Args:
        db: Database session
        server_name: MCP server name

    Returns:
        Number of deleted secrets
    """
    secrets = await get_secrets_by_server(db, server_name)
    count = len(secrets)
    for secret in secrets:
        await db.delete(secret)
    await db.commit()
    return count
