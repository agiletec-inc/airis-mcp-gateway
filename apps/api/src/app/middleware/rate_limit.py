"""
Rate limiting middleware for API protection.

In-memory fixed window rate limiting. Note: This does NOT work across
multiple processes/instances. For production with multiple workers,
use Redis-backed rate limiting (see DEPLOYMENT.md).

Key priority: API-Key header > client IP
"""
import hashlib
import ipaddress
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from ..core.logging import get_logger


logger = get_logger(__name__)


# Configuration via environment variables
RATE_LIMIT_PER_IP = int(os.getenv("RATE_LIMIT_PER_IP", "100"))  # requests per minute
RATE_LIMIT_PER_API_KEY = int(os.getenv("RATE_LIMIT_PER_API_KEY", "1000"))  # requests per minute
RATE_LIMIT_WINDOW = 60  # seconds (fixed at 1 minute)

# Paths excluded from rate limiting (monitoring endpoints)
EXCLUDED_PATHS = frozenset({"/health", "/ready", "/metrics"})

# Trusted proxy CIDRs — only trust X-Forwarded-For from these sources.
# Default: Docker bridge + loopback. Override via TRUSTED_PROXIES env var
# (comma-separated CIDRs, e.g. "10.0.0.0/8,172.16.0.0/12").
_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
TRUSTED_PROXIES: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network(cidr.strip(), strict=False)
    for cidr in os.getenv("TRUSTED_PROXIES", _DEFAULT_TRUSTED).split(",")
    if cidr.strip()
]


@dataclass
class RateLimitEntry:
    """Rate limit state for a single key."""
    count: int = 0
    window_start: float = 0.0


class RateLimitStore:
    """
    In-memory rate limit storage.

    Uses fixed window algorithm:
    - Each key gets a count and window_start timestamp
    - When window expires, count resets
    - Simple but can have burst at window boundaries

    Thread-safe for single process, but NOT shared across processes.
    """

    def __init__(self):
        self._store: dict[str, RateLimitEntry] = defaultdict(RateLimitEntry)

    def check_and_increment(self, key: str, limit: int, window: int = RATE_LIMIT_WINDOW) -> tuple[bool, int]:
        """
        Check rate limit and increment counter.

        Args:
            key: Rate limit key (API key or IP)
            limit: Maximum requests allowed in window
            window: Time window in seconds

        Returns:
            Tuple of (allowed: bool, retry_after: int seconds)
        """
        now = time.time()
        entry = self._store[key]

        # Check if window has expired
        if now - entry.window_start >= window:
            # Reset window
            entry.count = 1
            entry.window_start = now
            return (True, 0)

        # Check limit
        if entry.count >= limit:
            # Calculate retry-after (time until window resets)
            retry_after = int(window - (now - entry.window_start)) + 1
            return (False, retry_after)

        # Increment and allow
        entry.count += 1
        return (True, 0)

    def clear(self):
        """Clear all entries. Useful for testing."""
        self._store.clear()

    def cleanup_expired(self, window: int = RATE_LIMIT_WINDOW) -> int:
        """Drop entries whose window has already expired.

        The fixed-window algorithm never needs stale entries: if the window
        has passed, the very next request for that key would reset it
        anyway. Returning the stale entries to the garbage collector keeps
        memory bounded for workloads with a long tail of one-shot clients
        (short-lived CDN edges, CI runners, pentest scanners, …).

        Args:
            window: Rate limit window in seconds. Entries older than
                ``window`` seconds are evicted.

        Returns:
            Number of entries removed.
        """
        now = time.time()
        expired_keys = [
            key
            for key, entry in self._store.items()
            if now - entry.window_start >= window
        ]
        for key in expired_keys:
            self._store.pop(key, None)
        return len(expired_keys)

    def __len__(self) -> int:
        return len(self._store)


def _hash_key(key: str) -> str:
    """Return a short, non-reversible identifier for a rate-limit key.

    Used in log messages so the raw API key / IP never hits the log stream.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


# Global store instance
_rate_limit_store = RateLimitStore()


def get_rate_limit_store() -> RateLimitStore:
    """Get the global rate limit store."""
    return _rate_limit_store


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware.

    - Extracts key from Authorization header (Bearer token) or client IP
    - Applies different limits for API-key vs IP-based requests
    - Skips rate limiting for monitoring endpoints
    - Returns 429 with Retry-After header when limit exceeded
    """

    def __init__(self, app, store: Optional[RateLimitStore] = None):
        super().__init__(app)
        self.store = store or get_rate_limit_store()

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for monitoring endpoints
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        # Determine key and limit
        key, limit = self._get_key_and_limit(request)

        # Check rate limit
        allowed, retry_after = self.store.check_and_increment(key, limit)

        if not allowed:
            logger.warning(
                "Rate limit exceeded for key=%s limit=%d/min",
                _hash_key(key),
                limit,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)

    def _get_key_and_limit(self, request: Request) -> tuple[str, int]:
        """
        Extract rate limit key and determine applicable limit.

        Priority: API-Key (Authorization: Bearer) > Client IP

        Returns:
            Tuple of (key: str, limit: int)
        """
        # Check for API key in Authorization header
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            api_key = auth_header[7:].strip()
            if api_key:
                return (f"apikey:{api_key}", RATE_LIMIT_PER_API_KEY)

        # Fall back to client IP
        client_ip = self._get_client_ip(request)
        return (f"ip:{client_ip}", RATE_LIMIT_PER_IP)

    @staticmethod
    def _is_trusted_proxy(ip_str: str) -> bool:
        """Check if an IP address belongs to a trusted proxy network."""
        try:
            addr = ipaddress.ip_address(ip_str)
            return any(addr in network for network in TRUSTED_PROXIES)
        except ValueError:
            return False

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, considering proxy headers only from trusted proxies."""
        direct_ip = request.client.host if request.client else "unknown"

        # Only trust proxy headers when the direct connection is from a trusted proxy
        if not self._is_trusted_proxy(direct_ip):
            return direct_ip

        # Check X-Forwarded-For (for reverse proxy setups)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Take the first IP (original client)
            return forwarded.split(",")[0].strip()

        # Check X-Real-IP (nginx style)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        return direct_ip
