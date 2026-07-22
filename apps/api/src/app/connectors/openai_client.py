from __future__ import annotations

from typing import Any, Dict

import httpx

from .base import BaseConnector


class OpenAIClient(BaseConnector):
    """Minimal OpenAI connector leveraging credential provider."""

    _PROBE_URL = "https://api.openai.com/v1/models"
    _EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

    async def _headers(self) -> dict[str, str]:
        secret = await self._creds.get(self.connector_id)
        if not secret or not secret.get("value"):
            raise RuntimeError("CREDENTIALS_NOT_SET")
        return {"Authorization": f"Bearer {secret['value']}"}

    async def light_probe(self) -> None:
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(self._PROBE_URL, headers=headers)
            response.raise_for_status()

    async def invoke(self, tool: str, args: Dict[str, Any]) -> Any:
        headers = await self._headers()
        payload = args or {}
        url = self._EMBEDDINGS_URL if tool == "embeddings" else self._PROBE_URL
        async with httpx.AsyncClient(timeout=30.0) as client:
            if tool == "models.list":
                resp = await client.get(
                    self._PROBE_URL, headers=headers, params=payload
                )
            else:
                resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()
