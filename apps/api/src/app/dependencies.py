from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .core.crypto import load_default_cipher
from .core.credentials_provider import CredentialProvider
from .core.registry import MCPRegistry
from .core.database import AsyncSessionLocal
from .repositories import CredentialRepository, SettingRepository


@lru_cache(maxsize=1)
def _container() -> tuple[CredentialProvider, MCPRegistry, SettingRepository]:
    cipher = load_default_cipher()
    credential_repo = CredentialRepository(AsyncSessionLocal, cipher)  # pyright: ignore[reportArgumentType]
    provider = CredentialProvider(credential_repo)
    registry = MCPRegistry(provider)
    settings_repo = SettingRepository(AsyncSessionLocal)  # pyright: ignore[reportArgumentType]
    return provider, registry, settings_repo


@dataclass
class AdminContext:
    credential_provider: CredentialProvider
    registry: MCPRegistry
    settings_repo: SettingRepository
    actor: str = "system"


def get_admin_context() -> AdminContext:
    provider, registry, settings_repo = _container()
    return AdminContext(
        credential_provider=provider,
        registry=registry,
        settings_repo=settings_repo,
    )
