"""
HTTP metrics middleware for request monitoring.

Collects:
- Request count by method, path, status
- Request latency (p50, p95, p99)

Note: In-memory storage - resets on restart.
For production with multiple workers, use Prometheus client library.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..core.logging import get_logger


logger = get_logger(__name__)


@dataclass
class LatencyStats:
    """Latency statistics with percentile calculation."""

    samples: list[float] = field(default_factory=list)
    max_samples: int = 1000  # Keep last N samples

    def add(self, latency_ms: float) -> None:
        """Add a latency sample."""
        self.samples.append(latency_ms)
        # Trim to max samples (keep most recent)
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples :]

    def percentile(self, p: float) -> Optional[float]:
        """Calculate percentile (0-100)."""
        if not self.samples:
            return None
        sorted_samples = sorted(self.samples)
        index = int(len(sorted_samples) * p / 100)
        index = min(index, len(sorted_samples) - 1)
        return sorted_samples[index]

    @property
    def p50(self) -> Optional[float]:
        return self.percentile(50)

    @property
    def p95(self) -> Optional[float]:
        return self.percentile(95)

    @property
    def p99(self) -> Optional[float]:
        return self.percentile(99)


class HTTPMetricsStore:
    """
    In-memory HTTP metrics storage.

    Thread-safe for single process (GIL protects dict operations).
    """

    def __init__(self):
        # Counter: {(method, path, status): count}
        self._request_count: dict[tuple[str, str, int], int] = defaultdict(int)
        # Latency by path: {path: LatencyStats}
        self._latency: dict[str, LatencyStats] = defaultdict(LatencyStats)

    def record_request(
        self, method: str, path: str, status_code: int, latency_ms: float
    ) -> None:
        """Record a completed request."""
        # Normalize path (remove query params, collapse IDs)
        normalized_path = self._normalize_path(path)

        self._request_count[(method, normalized_path, status_code)] += 1
        self._latency[normalized_path].add(latency_ms)

    def _normalize_path(self, path: str) -> str:
        """
        Normalize path for aggregation.

        - Remove query params
        - Collapse UUID-like segments to {id}
        """
        # Remove query params
        path = path.split("?")[0]

        # Collapse UUID segments (simplistic - just long hex strings)
        import re

        path = re.sub(r"/[0-9a-f]{8,}", "/{id}", path, flags=re.IGNORECASE)

        return path

    def get_request_counts(self) -> dict[tuple[str, str, int], int]:
        """Get all request counts."""
        return dict(self._request_count)

    def get_latency_stats(self) -> dict[str, dict[str, Optional[float]]]:
        """Get latency stats for all paths."""
        return {
            path: {
                "p50": stats.p50,
                "p95": stats.p95,
                "p99": stats.p99,
            }
            for path, stats in self._latency.items()
        }

    def clear(self) -> None:
        """Clear all metrics. Useful for testing."""
        self._request_count.clear()
        self._latency.clear()


# Global store instance
_http_metrics_store = HTTPMetricsStore()


def get_http_metrics_store() -> HTTPMetricsStore:
    """Get the global HTTP metrics store."""
    return _http_metrics_store


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware that collects HTTP metrics.

    Records request count and latency for monitoring.
    """

    def __init__(self, app, store: Optional[HTTPMetricsStore] = None):
        super().__init__(app)
        self.store = store or get_http_metrics_store()

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        response = await call_next(request)

        # Calculate latency
        latency_ms = (time.perf_counter() - start_time) * 1000

        # Record metrics
        self.store.record_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

        return response
