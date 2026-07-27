"""
Logging context middleware for request tracing.

Sets request_id in ContextVar so all log messages include it.
Must be registered AFTER RequestIDMiddleware (so it runs after request_id is set).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..core.logging import set_request_id, get_logger


logger = get_logger(__name__)


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware that sets logging context from request.

    - Reads request_id from request.state (set by RequestIDMiddleware)
    - Sets it in ContextVar for structured logging
    - Logs request start/end with timing
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Get request_id from state (set by RequestIDMiddleware)
        request_id = getattr(request.state, "request_id", None)
        set_request_id(request_id)

        # Log request start
        client_ip = self._get_client_ip(request)
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={"client_ip": client_ip},
        )

        try:
            response = await call_next(request)

            # Log request end
            logger.info(
                f"Request completed: {request.method} {request.url.path} -> {response.status_code}"
            )

            return response

        except Exception:
            # Log exception (will include request_id)
            logger.exception(f"Request failed: {request.method} {request.url.path}")
            raise

        finally:
            # Clear context
            set_request_id(None)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, considering proxy headers."""
        # Check X-Forwarded-For first (for reverse proxy setups)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Take the first IP (original client)
            return forwarded.split(",")[0].strip()

        # Fall back to direct connection
        if request.client:
            return request.client.host

        return "unknown"
