"""
Request ID middleware for request tracing.

Generates or propagates X-Request-ID header for all requests.
This is the foundation for structured logging and debugging.
"""

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures every request has a unique ID.

    - If X-Request-ID header is provided, it's propagated
    - Otherwise, a new UUID is generated
    - The ID is stored in request.state.request_id for downstream use
    - The ID is always returned in the response header
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Get existing ID or generate new one
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        # Store in request.state for logging/metrics to access
        request.state.request_id = request_id

        response = await call_next(request)

        # Always return the ID in response header
        response.headers[REQUEST_ID_HEADER] = request_id

        return response
