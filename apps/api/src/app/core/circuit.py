from __future__ import annotations

import random
import time
from dataclasses import dataclass


@dataclass
class CircuitState:
    state: str
    retry_at_ms: float


class Circuit:
    """Simple circuit breaker implementation per connector."""

    def __init__(self, base_ms: int = 1_000, max_ms: int = 30_000):
        self._base = base_ms
        self._max = max_ms
        self._failures = 0
        self._state = "CLOSED"
        self._retry_at_ms = 0.0

    @property
    def state(self) -> CircuitState:
        return CircuitState(self._state, self._retry_at_ms)

    def allow(self) -> bool:
        if self._state == "OPEN":
            return time.time() * 1000 >= self._retry_at_ms
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._state = "CLOSED"
        self._retry_at_ms = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        backoff = min(self._base * (2 ** (self._failures - 1)), self._max)
        jitter = random.randint(0, int(backoff * 0.2))  # nosec B311: jitter is not security-sensitive
        self._state = "OPEN"
        self._retry_at_ms = time.time() * 1000 + backoff + jitter

    def half_open(self) -> None:
        self._state = "HALF_OPEN"
