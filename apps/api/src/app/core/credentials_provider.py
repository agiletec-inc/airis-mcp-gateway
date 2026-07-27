from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from ..repositories.credentials import CredentialRepository

logger = logging.getLogger(__name__)

Subscriber = Callable[[str, int], None]


class CredentialProvider:
    """Caches credentials and notifies subscribers on change."""

    def __init__(
        self,
        repo: CredentialRepository,
        ttl_ms: int = 60_000,
    ):
        self._repo = repo
        self._ttl = ttl_ms
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._subs: List[Subscriber] = []
        self._lock = asyncio.Lock()

    def subscribe(self, fn: Subscriber) -> None:
        self._subs.append(fn)

    async def get(self, credential_id: str) -> Optional[dict[str, Any]]:
        now_ms = time.time() * 1000
        cached = self._cache.get(credential_id)
        if cached and cached["exp"] > now_ms:
            return cached["val"]

        async with self._lock:
            cached = self._cache.get(credential_id)
            if cached and cached["exp"] > now_ms:
                return cached["val"]

            record = await self._repo.load(credential_id)
            if not record:
                self._cache.pop(credential_id, None)
                return None

            self._cache[credential_id] = {
                "val": record,
                "exp": now_ms + self._ttl,
            }
            return record

    async def set(
        self,
        credential_id: str,
        provider: str,
        value: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        result = await self._repo.save(credential_id, provider, value, actor)
        self._cache.pop(credential_id, None)

        timestamp = int(time.time())
        for subscriber in list(self._subs):
            try:
                subscriber(credential_id, timestamp)
            except Exception as exc:  # noqa: BLE001
                # Subscribers should be robust; ignore failure to avoid cascade.
                logger.debug(
                    "Subscriber notification failed for %s: %s", credential_id, exc
                )
                continue

        return result
