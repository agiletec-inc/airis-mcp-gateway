"""
Unit tests for ProcessManager.

Tests cover:
- Initialization and server registration
- Server filtering (hot/cold/enabled)
- Tool routing
- Server enable/disable
- Status reporting
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.process_manager import ProcessManager
from app.core.process_runner import ProcessState
from app.core.mcp_config_loader import McpServerConfig, ServerMode


@pytest.fixture
def mock_config():
    """Create mock MCP config."""
    return {
        "mcpServers": {
            "test-server-hot": {
                "command": "npx",
                "args": ["-y", "test-server"],
                "enabled": True,
                "mode": "hot"
            },
            "test-server-cold": {
                "command": "uvx",
                "args": ["test-cold"],
                "enabled": True,
                "mode": "cold"
            },
            "test-server-disabled": {
                "command": "npx",
                "args": ["disabled"],
                "enabled": False,
                "mode": "hot"
            }
        }
    }


@pytest.fixture
def mock_server_configs():
    """Create mock McpServerConfig objects."""
    from app.core.mcp_config_loader import ServerType
    return {
        "test-hot": McpServerConfig(
            name="test-hot",
            server_type=ServerType.PROCESS,
            command="npx",
            args=["-y", "test"],
            env={},
            enabled=True,
            mode=ServerMode.HOT
        ),
        "test-cold": McpServerConfig(
            name="test-cold",
            server_type=ServerType.PROCESS,
            command="uvx",
            args=["test"],
            env={},
            enabled=True,
            mode=ServerMode.COLD
        ),
        "test-disabled": McpServerConfig(
            name="test-disabled",
            server_type=ServerType.PROCESS,
            command="npx",
            args=["test"],
            env={},
            enabled=False,
            mode=ServerMode.HOT
        ),
    }


class TestProcessManagerInit:
    """Test ProcessManager initialization."""

    def test_init_default_values(self):
        """Test default initialization values."""
        manager = ProcessManager()
        assert manager._config_path is None
        assert manager._idle_timeout == 120
        assert manager._runners == {}
        assert manager._server_configs == {}
        assert manager._initialized is False

    def test_init_custom_values(self):
        """Test custom initialization values."""
        manager = ProcessManager(config_path="/custom/path", idle_timeout=60)
        assert manager._config_path == "/custom/path"
        assert manager._idle_timeout == 60


class TestServerFiltering:
    """Test server filtering methods."""

    @pytest.fixture
    def manager_with_servers(self, mock_server_configs):
        """Create manager with pre-configured servers."""
        manager = ProcessManager()
        manager._server_configs = mock_server_configs
        manager._runners = {
            name: MagicMock() for name in mock_server_configs.keys()
        }
        manager._initialized = True
        return manager

    def test_get_server_names(self, manager_with_servers):
        """Test getting all server names."""
        names = manager_with_servers.get_server_names()
        assert set(names) == {"test-hot", "test-cold", "test-disabled"}

    def test_get_enabled_servers(self, manager_with_servers):
        """Test getting enabled servers only."""
        enabled = manager_with_servers.get_enabled_servers()
        assert set(enabled) == {"test-hot", "test-cold"}
        assert "test-disabled" not in enabled

    def test_get_hot_servers(self, manager_with_servers):
        """Test getting HOT mode servers only."""
        hot = manager_with_servers.get_hot_servers()
        assert hot == ["test-hot"]
        assert "test-cold" not in hot
        assert "test-disabled" not in hot

    def test_get_cold_servers(self, manager_with_servers):
        """Test getting COLD mode servers only."""
        cold = manager_with_servers.get_cold_servers()
        assert cold == ["test-cold"]
        assert "test-hot" not in cold

    def test_is_process_server(self, manager_with_servers):
        """Test checking if server is managed."""
        assert manager_with_servers.is_process_server("test-hot") is True
        assert manager_with_servers.is_process_server("unknown") is False


class TestServerEnableDisable:
    """Test server enable/disable functionality."""

    @pytest.fixture
    def manager_with_runner(self, mock_server_configs):
        """Create manager with mock runner."""
        manager = ProcessManager()
        manager._server_configs = mock_server_configs

        mock_runner = MagicMock()
        mock_runner.state = ProcessState.RUNNING
        mock_runner.stop = AsyncMock()

        manager._runners = {
            "test-hot": mock_runner,
            "test-cold": MagicMock(),
            "test-disabled": MagicMock(),
        }
        manager._tool_to_server = {"tool1": "test-hot", "tool2": "test-cold"}
        return manager

    @pytest.mark.asyncio
    async def test_enable_server(self, manager_with_runner):
        """Test enabling a disabled server."""
        # Disable first
        manager_with_runner._server_configs["test-disabled"].enabled = False

        result = await manager_with_runner.enable_server("test-disabled")
        assert result is True
        assert manager_with_runner._server_configs["test-disabled"].enabled is True

    @pytest.mark.asyncio
    async def test_enable_unknown_server(self, manager_with_runner):
        """Test enabling unknown server returns False."""
        result = await manager_with_runner.enable_server("unknown")
        assert result is False

    @pytest.mark.asyncio
    async def test_disable_server(self, manager_with_runner):
        """Test disabling a server stops its process."""
        result = await manager_with_runner.disable_server("test-hot")

        assert result is True
        assert manager_with_runner._server_configs["test-hot"].enabled is False
        manager_with_runner._runners["test-hot"].stop.assert_called_once()
        # Tool mapping should be removed
        assert "tool1" not in manager_with_runner._tool_to_server

    @pytest.mark.asyncio
    async def test_disable_unknown_server(self, manager_with_runner):
        """Test disabling unknown server returns False."""
        result = await manager_with_runner.disable_server("unknown")
        assert result is False


class TestToolRouting:
    """Test tool routing functionality."""

    @pytest.fixture
    def manager_with_tools(self, mock_server_configs):
        """Create manager with tool mappings."""
        manager = ProcessManager()
        manager._server_configs = mock_server_configs
        manager._tool_to_server = {
            "get_time": "test-hot",
            "search": "test-cold",
        }

        mock_runner = MagicMock()
        mock_runner.call_tool = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "result": {"content": [{"type": "text", "text": "success"}]}
        })

        manager._runners = {
            "test-hot": mock_runner,
            "test-cold": mock_runner,
        }
        return manager

    @pytest.mark.asyncio
    async def test_call_tool_routes_correctly(self, manager_with_tools):
        """Test tool call routes to correct server."""
        result = await manager_with_tools.call_tool("get_time", {"tz": "UTC"})

        assert "result" in result
        manager_with_tools._runners["test-hot"].call_tool.assert_called_once_with(
            "get_time", {"tz": "UTC"}
        )

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self, manager_with_tools):
        """Test calling unknown tool returns error."""
        # Mock list_tools to return empty
        manager_with_tools._runners["test-hot"].ensure_ready_with_error = AsyncMock(return_value=(True, None))
        manager_with_tools._runners["test-hot"].tools = []
        manager_with_tools._runners["test-cold"].ensure_ready_with_error = AsyncMock(return_value=(True, None))
        manager_with_tools._runners["test-cold"].tools = []

        result = await manager_with_tools.call_tool("unknown_tool", {})

        assert "error" in result
        assert result["error"]["code"] == -32601
        assert "not found" in result["error"]["message"].lower()


class TestServerStatus:
    """Test server status reporting."""

    @pytest.fixture
    def manager_for_status(self, mock_server_configs):
        """Create manager for status tests."""
        manager = ProcessManager()
        manager._server_configs = {
            "test-server": mock_server_configs["test-hot"]
        }

        mock_runner = MagicMock()
        mock_runner.state = ProcessState.RUNNING
        mock_runner.tools = [{"name": "tool1"}, {"name": "tool2"}]
        mock_runner.get_metrics = MagicMock(return_value={
            "requests": 10,
            "errors": 1
        })

        manager._runners = {"test-server": mock_runner}
        return manager

    def test_get_server_status(self, manager_for_status):
        """Test getting server status."""
        status = manager_for_status.get_server_status("test-server")

        assert status["name"] == "test-server"
        assert status["type"] == "process"
        assert status["enabled"] is True
        assert status["mode"] == "hot"
        assert status["state"] == "running"
        assert status["tools_count"] == 2

    def test_get_server_status_with_metrics(self, manager_for_status):
        """Test getting server status with metrics."""
        status = manager_for_status.get_server_status("test-server", include_metrics=True)

        assert "metrics" in status
        assert status["metrics"]["requests"] == 10

    def test_get_unknown_server_status(self, manager_for_status):
        """Test getting status of unknown server."""
        status = manager_for_status.get_server_status("unknown")
        assert "error" in status

    def test_get_all_status(self, manager_for_status):
        """Test getting all server statuses."""
        statuses = manager_for_status.get_all_status()

        assert len(statuses) == 1
        assert statuses[0]["name"] == "test-server"


class TestShutdown:
    """Test shutdown functionality."""

    @pytest.mark.asyncio
    async def test_shutdown_stops_all_runners(self):
        """Test shutdown stops all running processes."""
        manager = ProcessManager()

        runner1 = MagicMock()
        runner1.state = ProcessState.RUNNING
        runner1.stop = AsyncMock()

        runner2 = MagicMock()
        runner2.state = ProcessState.STOPPED
        runner2.stop = AsyncMock()

        runner3 = MagicMock()
        runner3.state = ProcessState.RUNNING
        runner3.stop = AsyncMock()

        manager._runners = {
            "server1": runner1,
            "server2": runner2,
            "server3": runner3,
        }

        await manager.shutdown()

        # Only running servers should be stopped
        runner1.stop.assert_called_once()
        runner2.stop.assert_not_called()  # Already stopped
        runner3.stop.assert_called_once()


class TestCallToolOnServer:
    """Test direct server tool calls."""

    @pytest.fixture
    def manager_direct_call(self, mock_server_configs):
        """Create manager for direct call tests."""
        manager = ProcessManager()
        manager._server_configs = mock_server_configs

        mock_runner = MagicMock()
        mock_runner.call_tool = AsyncMock(return_value={
            "jsonrpc": "2.0",
            "result": {"success": True}
        })

        manager._runners = {
            "test-hot": mock_runner,
            "test-cold": mock_runner,
            "test-disabled": mock_runner,
        }
        return manager

    @pytest.mark.asyncio
    async def test_call_tool_on_server_success(self, manager_direct_call):
        """Test calling tool on specific server."""
        result = await manager_direct_call.call_tool_on_server(
            "test-hot", "my_tool", {"arg": "value"}
        )

        assert "result" in result
        assert result["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_call_tool_on_unknown_server(self, manager_direct_call):
        """Test calling tool on unknown server."""
        result = await manager_direct_call.call_tool_on_server(
            "unknown", "my_tool", {}
        )

        assert "error" in result
        assert "not found" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_call_tool_on_disabled_server(self, manager_direct_call):
        """Test calling tool on disabled server."""
        result = await manager_direct_call.call_tool_on_server(
            "test-disabled", "my_tool", {}
        )

        assert "error" in result
        assert "not enabled" in result["error"]["message"].lower()
