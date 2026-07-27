from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..models import MCPSetting


class SettingRepository:
    """Runtime flags for MCP connectors."""

    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def list(self) -> list[MCPSetting]:
        async with self._session_factory() as session:
            result = await session.execute(select(MCPSetting))
            return list(result.scalars().all())

    async def get(self, setting_id: str) -> Optional[MCPSetting]:
        async with self._session_factory() as session:
            return await session.get(MCPSetting, setting_id)

    async def enable(self, setting_id: str) -> MCPSetting:
        return await self._update_enabled(setting_id, True)

    async def disable(self, setting_id: str) -> MCPSetting:
        return await self._update_enabled(setting_id, False)

    async def _update_enabled(self, setting_id: str, flag: bool) -> MCPSetting:
        async with self._session_factory() as session:
            existing = await session.get(MCPSetting, setting_id)
            if existing:
                existing.enabled = flag
            else:
                existing = MCPSetting(id=setting_id, enabled=flag)
                session.add(existing)

            await session.commit()
            return existing

    async def upsert_config(
        self,
        setting_id: str,
        config_json: str,
        enabled: bool | None = None,
    ) -> MCPSetting:
        async with self._session_factory() as session:
            existing = await session.get(MCPSetting, setting_id)
            if existing:
                existing.config_json = config_json
                if enabled is not None:
                    existing.enabled = enabled
            else:
                existing = MCPSetting(
                    id=setting_id,
                    enabled=enabled if enabled is not None else False,
                    config_json=config_json,
                )
                session.add(existing)
            await session.commit()
            return existing
