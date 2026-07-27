from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from .circuit import Circuit
from .credentials_provider import CredentialProvider
from ..connectors import build_connector

logger = logging.getLogger(__name__)


class MCPRegistry:
    """Lazy connector registry with hot-reload support."""

    def __init__(self, creds: CredentialProvider):
        self._creds = creds
        self._clients: Dict[str, Any] = {}
        self._circuits: Dict[str, Circuit] = {}
        self._creds.subscribe(self._on_cred_changed)

    def _on_cred_changed(self, connector_id: str, _ts: int) -> None:
        circuit = self._circuits.get(connector_id)
        client = self._clients.get(connector_id)
        if client:
            try:
                client.reset_auth()
            except Exception as exc:  # noqa: BLE001
                logger.warning("hot-reload reset failed for %s: %s", connector_id, exc)
        if circuit:
            circuit.half_open()
        logger.info("credentials hot-reloaded for connector %s", connector_id)

    async def _get(self, connector_id: str) -> Tuple[Any, Circuit]:
        if connector_id not in self._clients:
            self._clients[connector_id] = build_connector(connector_id, self._creds)
            self._circuits[connector_id] = Circuit()
        return self._clients[connector_id], self._circuits[connector_id]

    async def probe(self, connector_id: str) -> bool:
        client, circuit = await self._get(connector_id)
        try:
            await client.light_probe()
        except Exception as exc:  # noqa: BLE001
            circuit.record_failure()
            logger.warning("probe failed for %s: %s", connector_id, exc)
            return False
        circuit.record_success()
        return True

    async def invoke(
        self,
        connector_id: str,
        tool: str,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        client, circuit = await self._get(connector_id)
        if not circuit.allow():
            return {
                "ok": False,
                "error": "CIRCUIT_OPEN",
                "retryAt": circuit.state.retry_at_ms,
            }

        try:
            result = await client.invoke(tool, args)
        except Exception as exc:  # noqa: BLE001
            circuit.record_failure()
            return {"ok": False, "error": str(exc)}

        circuit.record_success()
        return {"ok": True, "data": result}
