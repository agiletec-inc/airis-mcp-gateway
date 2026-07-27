"""API-key authentication dependency for high-impact endpoints.

The ``OptionalBearerAuth`` middleware already gates every request when
``AIRIS_API_KEY`` is set. ``verify_api_key`` adds a second, explicit layer
for the ``/process/*`` admin/mutation endpoints (enable/disable, tool calls,
raw JSON-RPC) so they:

- stay protected even if the middleware is later reordered or removed, and
- fail closed in any non-development environment that is missing a key,
  instead of silently serving admin endpoints unauthenticated.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from .config import settings
from .logging import get_logger

logger = get_logger(__name__)


def verify_api_key(request: Request) -> None:
    """FastAPI dependency that enforces bearer-token authentication.

    Behaviour:

    - ``AIRIS_API_KEY`` set: a valid ``Authorization: Bearer <key>`` header
      is required, otherwise ``401``.
    - ``AIRIS_API_KEY`` unset, ``ENV=development``: open access. This keeps
      local debugging (e.g. ``curl localhost:9400/process/servers``) working;
      ``validate_environment()`` already logs a startup warning.
    - ``AIRIS_API_KEY`` unset, any other ``ENV`` (staging/production): fail
      closed with ``503``. Admin endpoints must never be exposed
      unauthenticated outside local development.
    """
    api_key = (settings.AIRIS_API_KEY or "").strip()

    if api_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if secrets.compare_digest(token, api_key):
                return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
        )

    # No API key configured.
    if settings.ENV != "development":
        logger.error(
            "Refusing unauthenticated access to a protected endpoint: "
            "AIRIS_API_KEY is not set (ENV=%s).",
            settings.ENV,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "This endpoint is disabled: AIRIS_API_KEY is not configured. "
                "Set AIRIS_API_KEY to enable authenticated access."
            ),
        )

    # Development only: open access for local debugging.
    return
