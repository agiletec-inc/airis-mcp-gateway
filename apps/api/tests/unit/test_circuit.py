"""
Unit tests for Circuit Breaker.

Tests cover:
- Initial state
- Allow/deny logic
- Success/failure recording
- Exponential backoff
- State transitions
"""

import time
from unittest.mock import patch

from app.core.circuit import Circuit, CircuitState


class TestCircuitInitialization:
    """Test Circuit initialization."""

    def test_default_values(self):
        """Test circuit initializes with default values."""
        circuit = Circuit()
        assert circuit._base == 1_000
        assert circuit._max == 30_000
        assert circuit._failures == 0
        assert circuit._state == "CLOSED"

    def test_custom_values(self):
        """Test circuit with custom values."""
        circuit = Circuit(base_ms=500, max_ms=10_000)
        assert circuit._base == 500
        assert circuit._max == 10_000


class TestCircuitState:
    """Test CircuitState dataclass."""

    def test_state_property(self):
        """Test state property returns CircuitState."""
        circuit = Circuit()
        state = circuit.state

        assert isinstance(state, CircuitState)
        assert state.state == "CLOSED"
        assert state.retry_at_ms == 0.0


class TestCircuitAllow:
    """Test allow() method."""

    def test_closed_circuit_allows(self):
        """Test closed circuit always allows."""
        circuit = Circuit()
        assert circuit.allow() is True

    def test_open_circuit_denies_before_retry_time(self):
        """Test open circuit denies before retry time."""
        circuit = Circuit()
        circuit._state = "OPEN"
        circuit._retry_at_ms = time.time() * 1000 + 10_000  # 10s in future

        assert circuit.allow() is False

    def test_open_circuit_allows_after_retry_time(self):
        """Test open circuit allows after retry time."""
        circuit = Circuit()
        circuit._state = "OPEN"
        circuit._retry_at_ms = time.time() * 1000 - 1_000  # 1s in past

        assert circuit.allow() is True

    def test_half_open_allows(self):
        """Test half-open circuit allows (not OPEN state)."""
        circuit = Circuit()
        circuit.half_open()
        assert circuit._state == "HALF_OPEN"
        assert circuit.allow() is True


class TestCircuitSuccess:
    """Test record_success() method."""

    def test_success_resets_failures(self):
        """Test success resets failure count."""
        circuit = Circuit()
        circuit._failures = 5
        circuit._state = "OPEN"

        circuit.record_success()

        assert circuit._failures == 0
        assert circuit._state == "CLOSED"
        assert circuit._retry_at_ms == 0.0


class TestCircuitFailure:
    """Test record_failure() method."""

    def test_failure_opens_circuit(self):
        """Test failure opens the circuit."""
        circuit = Circuit()
        circuit.record_failure()

        assert circuit._failures == 1
        assert circuit._state == "OPEN"
        assert circuit._retry_at_ms > time.time() * 1000

    def test_exponential_backoff(self):
        """Test backoff increases exponentially."""
        circuit = Circuit(base_ms=1000, max_ms=30000)

        # First failure: base_ms = 1000
        circuit.record_failure()
        first_retry = circuit._retry_at_ms

        # Second failure: base_ms * 2 = 2000
        circuit.record_failure()
        second_retry = circuit._retry_at_ms

        # Second retry should be further in future than first
        # (accounting for jitter)
        assert second_retry > first_retry

    @patch("random.randint", return_value=0)  # No jitter
    def test_backoff_capped_at_max(self, mock_random):
        """Test backoff is capped at max_ms."""
        circuit = Circuit(base_ms=1000, max_ms=5000)

        # Record many failures to exceed max
        for _ in range(10):
            circuit.record_failure()

        # Calculate expected retry time (with max cap)
        expected_backoff = 5000  # Capped at max
        now = time.time() * 1000

        # retry_at should be approximately now + max_ms
        assert circuit._retry_at_ms <= now + expected_backoff + 100  # Small tolerance


class TestCircuitHalfOpen:
    """Test half_open() method."""

    def test_half_open_sets_state(self):
        """Test half_open sets state correctly."""
        circuit = Circuit()
        circuit._state = "OPEN"

        circuit.half_open()

        assert circuit._state == "HALF_OPEN"


class TestCircuitIntegration:
    """Integration tests for circuit breaker patterns."""

    def test_typical_failure_recovery_flow(self):
        """Test typical flow: closed -> open -> allow after timeout -> success -> closed."""
        circuit = Circuit(base_ms=10, max_ms=100)

        # Initial: closed
        assert circuit._state == "CLOSED"
        assert circuit.allow() is True

        # Failure: opens circuit
        circuit.record_failure()
        assert circuit._state == "OPEN"
        assert circuit.allow() is False

        # Wait for retry time (mock by setting past retry time)
        circuit._retry_at_ms = time.time() * 1000 - 1
        assert circuit.allow() is True

        # Success: closes circuit
        circuit.record_success()
        assert circuit._state == "CLOSED"
        assert circuit._failures == 0
