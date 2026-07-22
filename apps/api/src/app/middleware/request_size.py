"""
Request size limiting middleware.

Prevents large payloads from consuming excessive memory.
"""

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from ..core.logging import get_logger


logger = get_logger(__name__)


# Default 10MB limit
MAX_REQUEST_SIZE = int(os.getenv("MAX_REQUEST_SIZE", str(10 * 1024 * 1024)))


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that limits request body size.

    Returns 413 Payload Too Large if Content-Length exceeds limit.

    Note: This checks Content-Length header, not actual body size.
    For streaming requests without Content-Length, consider using
    Starlette's request body limit configuration.
    """

    def __init__(self, app, max_size: int = MAX_REQUEST_SIZE):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check Content-Length header
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                size = int(content_length)
                if size > self.max_size:
                    logger.warning(
                        f"Request too large: {size} bytes > {self.max_size} bytes limit"
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "payload_too_large",
                            "message": f"Request body too large. Maximum size is {self.max_size} bytes.",
                            "max_size": self.max_size,
                        },
                    )
            except ValueError:
                # Invalid Content-Length, let it through (will likely fail later)
                pass

        return await call_next(request)
