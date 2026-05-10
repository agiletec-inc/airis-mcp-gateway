"""
Simple bearer token authentication for single-user mode.

If AIRIS_API_KEY is not set, authentication is disabled (open access).
If set, all requests must include: Authorization: Bearer <key>
"""
import os
import secrets
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class OptionalBearerAuth(BaseHTTPMiddleware):
    """Bearer auth middleware - skips auth if AIRIS_API_KEY not set"""

    def __init__(self, app, api_key: str | None = None):
        super().__init__(app)
        self.api_key = api_key or os.getenv("AIRIS_API_KEY", "").strip()

    async def dispatch(self, request: Request, call_next):
        # Skip auth for health endpoints
        if request.url.path in ["/health", "/ready", "/"]:
            return await call_next(request)

        # Skip auth if no API key configured (open access)
        if not self.api_key:
            return await call_next(request)

        # Validate bearer token
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if secrets.compare_digest(token, self.api_key):
                return await call_next(request)

        raise HTTPException(status_code=401, detail="unauthorized")


def optional_bearer_auth(api_key: str | None = None):
    """Factory function to create auth middleware"""
    return lambda app: OptionalBearerAuth(app, api_key)
