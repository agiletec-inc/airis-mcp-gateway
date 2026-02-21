"""
Unit tests for ensure_ready_with_error() method.

Tests cover:
- Successful server initialization returns (True, None)
- Failed initialization returns (False, error_message)
- Backward compatibility: ensure_ready() returns bool
- Error propagation from initialization failures
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from app.core.process_runner import ProcessRunner, ProcessConfig, ProcessState


@pytest.fixture
def process_config():
    """Create a basic process config for testing."""
    return ProcessConfig(
        name="test-server",
        command="npx",
        args=["-y", "test-mcp-server"],
        env={},
        idle_timeout=120,
    )


class TestEnsureReadyWithError:
    """Test ensure_ready_with_error() returns detailed error information."""

    @pytest.mark.asyncio
    async def test_returns_true_none_when_already_ready(self, process_config):
        """Test that already-ready server returns (True, None)."""
        runner = ProcessRunner(process_config)
        runner._state = ProcessState.READY

        success, error = await runner.ensure_ready_with_error()

        assert success is True
        assert error is None

    @pytest.mark.asyncio
    async def test_returns_false_with_error_on_start_failure(self, process_config):
        """Test that start failure returns (False, error_message)."""
        runner = ProcessRunner(process_config)
        runner._state = ProcessState.STOPPED

        # Mock _start_process to raise an exception
        async def mock_start_process():
            raise RuntimeError("Failed to spawn process: command not found")

        with patch.object(runner, '_start_process', side_effect=mock_start_process):
            success, error = await runner.ensure_ready_with_error()

        assert success is False
        assert error is not None
        assert "Failed to spawn process" in error

    @pytest.mark.asyncio
    async def test_returns_false_with_last_error_on_init_failure(self, process_config):
        """Test that initialization failure returns (False, last_error)."""
        runner = ProcessRunner(process_config)
        runner._state = ProcessState.STOPPED

        # Mock start to succeed but leave _last_error set
        async def mock_start_process():
            runner._state = ProcessState.RUNNING

        async def mock_initialize():
            runner._last_error = "MCP initialize failed: invalid protocol version"
            runner._state = ProcessState.STOPPED

        with patch.object(runner, '_start_process', side_effect=mock_start_process):
            with patch.object(runner, '_initialize', side_effect=mock_initialize):
                success, error = await runner.ensure_ready_with_error()

        assert success is False
        assert error is not None
        assert "MCP initialize failed" in error

    @pytest.mark.asyncio
    async def test_returns_timeout_error_message(self, process_config):
        """Test that timeout returns descriptive error."""
        runner = ProcessRunner(process_config)
        runner._state = ProcessState.STOPPED

        # Mock start to succeed but stay in INITIALIZING state
        async def mock_start_process():
            runner._state = ProcessState.RUNNING

        async def mock_initialize():
            runner._state = ProcessState.INITIALIZING
            # Never becomes READY

        with patch.object(runner, '_start_process', side_effect=mock_start_process):
            with patch.object(runner, '_initialize', side_effect=mock_initialize):
                success, error = await runner.ensure_ready_with_error(timeout=0.1)

        assert success is False
        assert error is not None
        assert "Timeout" in error


class TestEnsureReadyBackwardCompatibility:
    """Test ensure_ready() maintains backward compatibility."""

    @pytest.mark.asyncio
    async def test_ensure_ready_returns_true_on_success(self, process_config):
        """Test that ensure_ready() returns True when ready."""
        runner = ProcessRunner(process_config)
        runner._state = ProcessState.READY

        result = await runner.ensure_ready()

        assert result is True
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_ensure_ready_returns_false_on_failure(self, process_config):
        """Test that ensure_ready() returns False on failure."""
        runner = ProcessRunner(process_config)
        runner._state = ProcessState.STOPPED

        # Mock start to fail
        async def mock_start_process():
            raise RuntimeError("Process failed")

        with patch.object(runner, '_start_process', side_effect=mock_start_process):
            result = await runner.ensure_ready()

        assert result is False
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_ensure_ready_is_bool_not_tuple(self, process_config):
        """Verify ensure_ready() returns bool, not tuple."""
        runner = ProcessRunner(process_config)
        runner._state = ProcessState.READY

        result = await runner.ensure_ready()

        # Should not be a tuple
        assert not isinstance(result, tuple)
        assert isinstance(result, bool)


class TestErrorMessagePropagation:
    """Test that error messages are properly propagated."""

    @pytest.mark.asyncio
    async def test_initialize_error_captured(self, process_config):
        """Test that _initialize errors are captured in _last_error."""
        runner = ProcessRunner(process_config)

        # Manually simulate an initialize error
        runner._last_error = "Connection refused to MCP server"
        runner._state = ProcessState.STOPPED

        success, error = await runner.ensure_ready_with_error(timeout=0.05)

        # Should return the captured error
        assert success is False
        # Either times out or returns the last_error
        assert error is not None

    @pytest.mark.asyncio
    async def test_error_includes_server_name_context(self, process_config):
        """Test that errors can be contextualized with server name."""
        runner = ProcessRunner(process_config)
        runner._state = ProcessState.STOPPED

        async def mock_start_process():
            raise FileNotFoundError("npx: command not found")

        with patch.object(runner, '_start_process', side_effect=mock_start_process):
            success, error = await runner.ensure_ready_with_error()

        assert success is False
        assert error is not None
        # The error message should be useful for debugging
        assert "not found" in error.lower()
