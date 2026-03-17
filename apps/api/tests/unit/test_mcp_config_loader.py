"""
Unit tests for MCP Config Loader.

Tests cover:
- Server type classification
- Environment variable expansion
- Config loading and parsing
- Server filtering functions
"""
import pytest
import os
import json
import tempfile
from unittest.mock import patch

from app.core.mcp_config_loader import (
    ServerType,
    ServerMode,
    McpServerConfig,
    BehaviorConfig,
    classify_server_type,
    load_mcp_config,
    get_process_servers,
    get_docker_servers,
    get_enabled_servers,
    get_hot_servers,
    get_cold_servers,
    _expand_env_vars,
)


class TestServerTypeClassification:
    """Test server type classification."""

    @pytest.mark.parametrize("command,expected", [
        ("uvx", ServerType.PROCESS),
        ("npx", ServerType.PROCESS),
        ("node", ServerType.PROCESS),
        ("python", ServerType.PROCESS),
        ("python3", ServerType.PROCESS),
        ("deno", ServerType.PROCESS),
        ("bun", ServerType.PROCESS),
        ("sh", ServerType.PROCESS),
        ("/usr/bin/node", ServerType.PROCESS),
        ("/usr/local/bin/python3", ServerType.PROCESS),
    ])
    def test_process_commands(self, command, expected):
        """Test that process commands are correctly classified."""
        assert classify_server_type(command) == expected

    @pytest.mark.parametrize("command", [
        "docker",
        "unknown",
        "kubectl",
        "custom-server",
    ])
    def test_docker_commands(self, command):
        """Test that non-process commands default to DOCKER type."""
        assert classify_server_type(command) == ServerType.DOCKER


class TestEnvVarExpansion:
    """Test environment variable expansion."""

    def test_simple_var(self):
        """Test simple ${VAR} expansion."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            result = _expand_env_vars("prefix_${TEST_VAR}_suffix")
            assert result == "prefix_test_value_suffix"

    def test_var_with_default(self):
        """Test ${VAR:-default} expansion when var is not set."""
        # Ensure var is not set
        os.environ.pop("UNSET_VAR", None)
        result = _expand_env_vars("${UNSET_VAR:-default_value}")
        assert result == "default_value"

    def test_var_with_default_when_set(self):
        """Test ${VAR:-default} expansion when var is set."""
        with patch.dict(os.environ, {"SET_VAR": "actual_value"}):
            result = _expand_env_vars("${SET_VAR:-default_value}")
            assert result == "actual_value"

    def test_multiple_vars(self):
        """Test multiple variables in one string."""
        with patch.dict(os.environ, {"VAR1": "one", "VAR2": "two"}):
            result = _expand_env_vars("${VAR1} and ${VAR2}")
            assert result == "one and two"

    def test_no_expansion_needed(self):
        """Test string without variables."""
        result = _expand_env_vars("no variables here")
        assert result == "no variables here"

    def test_non_string_passthrough(self):
        """Test non-string values pass through unchanged."""
        result = _expand_env_vars(123)
        assert result == 123


class TestMcpServerConfig:
    """Test McpServerConfig dataclass."""

    def test_to_process_config(self):
        """Test conversion to ProcessConfig."""
        config = McpServerConfig(
            name="test-server",
            server_type=ServerType.PROCESS,
            command="npx",
            args=["-y", "test-package"],
            env={"KEY": "value"},
            enabled=True,
            mode=ServerMode.HOT,
        )

        process_config = config.to_process_config(idle_timeout=60)

        assert process_config.name == "test-server"
        assert process_config.command == "npx"
        assert process_config.args == ["-y", "test-package"]
        assert process_config.env == {"KEY": "value"}
        assert process_config.idle_timeout == 60

    def test_default_mode_is_cold(self):
        """Test that default mode is COLD."""
        config = McpServerConfig(
            name="test",
            server_type=ServerType.PROCESS,
            command="npx",
            args=[],
            env={},
            enabled=True,
        )
        assert config.mode == ServerMode.COLD


class TestLoadMcpConfig:
    """Test config file loading."""

    def test_load_valid_config(self):
        """Test loading a valid config file."""
        config_data = {
            "mcpServers": {
                "test-npx": {
                    "command": "npx",
                    "args": ["-y", "test-package"],
                    "enabled": True,
                    "mode": "hot"
                },
                "test-uvx": {
                    "command": "uvx",
                    "args": ["test-tool"],
                    "enabled": False,
                    "mode": "cold"
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            try:
                result = load_mcp_config(f.name)

                assert len(result) == 2
                assert "test-npx" in result
                assert "test-uvx" in result

                npx_server = result["test-npx"]
                assert npx_server.command == "npx"
                assert npx_server.enabled is True
                assert npx_server.mode == ServerMode.HOT
                assert npx_server.server_type == ServerType.PROCESS

                uvx_server = result["test-uvx"]
                assert uvx_server.enabled is False
                assert uvx_server.mode == ServerMode.COLD
            finally:
                os.unlink(f.name)

    def test_load_config_with_env_expansion(self):
        """Test that environment variables are expanded."""
        config_data = {
            "mcpServers": {
                "test-env": {
                    "command": "npx",
                    "args": ["-y", "server", "--key=${TEST_KEY}"],
                    "env": {"API_KEY": "${TEST_KEY:-default}"},
                    "enabled": True
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            try:
                with patch.dict(os.environ, {"TEST_KEY": "secret123"}):
                    result = load_mcp_config(f.name)

                    server = result["test-env"]
                    assert "--key=secret123" in server.args
                    assert server.env["API_KEY"] == "secret123"
            finally:
                os.unlink(f.name)

    def test_load_config_with_profiles(self):
        """Test loading config with profile references."""
        config_data = {
            "mcpServers": {
                "test-profile": {
                    "profile": "test-remote",
                    "enabled": True,
                    "mode": "cold"
                }
            },
            "profiles": {
                "test-remote": {
                    "command": "npx",
                    "args": ["-y", "mcp-remote", "http://example.com"]
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            try:
                result = load_mcp_config(f.name)

                assert "test-profile" in result
                server = result["test-profile"]
                assert server.command == "npx"
                assert "mcp-remote" in server.args
                assert server.runner == "remote"
            finally:
                os.unlink(f.name)

    def test_load_nonexistent_config(self):
        """Test loading non-existent config returns empty dict."""
        result = load_mcp_config("/nonexistent/path/config.json")
        assert result == {}

    def test_load_config_with_behavior(self):
        """Test that behavior field is parsed correctly."""
        config_data = {
            "mcpServers": {
                "test-behavior": {
                    "command": "npx",
                    "args": ["-y", "test-package"],
                    "enabled": True,
                    "mode": "hot",
                    "behavior": {
                        "triggers": ["implementing with library", "unsure about API"],
                        "instruction": "Lookup docs BEFORE writing code",
                        "priority": "high"
                    }
                },
                "test-no-behavior": {
                    "command": "npx",
                    "args": ["-y", "other-package"],
                    "enabled": True,
                    "mode": "cold"
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            try:
                result = load_mcp_config(f.name)

                # Server with behavior
                server = result["test-behavior"]
                assert server.behavior is not None
                assert isinstance(server.behavior, BehaviorConfig)
                assert server.behavior.triggers == ["implementing with library", "unsure about API"]
                assert server.behavior.instruction == "Lookup docs BEFORE writing code"
                assert server.behavior.priority == "high"

                # Server without behavior
                server_no = result["test-no-behavior"]
                assert server_no.behavior is None
            finally:
                os.unlink(f.name)

    def test_load_config_behavior_default_priority(self):
        """Test that behavior priority defaults to 'medium'."""
        config_data = {
            "mcpServers": {
                "test": {
                    "command": "npx",
                    "args": [],
                    "enabled": True,
                    "behavior": {
                        "triggers": ["some trigger"],
                        "instruction": "do something"
                    }
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            try:
                result = load_mcp_config(f.name)
                assert result["test"].behavior.priority == "medium"
            finally:
                os.unlink(f.name)

    def test_invalid_mode_defaults_to_cold(self):
        """Test that invalid mode defaults to COLD."""
        config_data = {
            "mcpServers": {
                "test": {
                    "command": "npx",
                    "args": [],
                    "enabled": True,
                    "mode": "invalid_mode"
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            try:
                result = load_mcp_config(f.name)
                assert result["test"].mode == ServerMode.COLD
            finally:
                os.unlink(f.name)


class TestServerFiltering:
    """Test server filtering functions."""

    @pytest.fixture
    def sample_config(self):
        """Create sample config for filtering tests."""
        return {
            "process-hot": McpServerConfig(
                name="process-hot",
                server_type=ServerType.PROCESS,
                command="npx",
                args=[],
                env={},
                enabled=True,
                mode=ServerMode.HOT,
            ),
            "process-cold": McpServerConfig(
                name="process-cold",
                server_type=ServerType.PROCESS,
                command="uvx",
                args=[],
                env={},
                enabled=True,
                mode=ServerMode.COLD,
            ),
            "process-disabled": McpServerConfig(
                name="process-disabled",
                server_type=ServerType.PROCESS,
                command="npx",
                args=[],
                env={},
                enabled=False,
                mode=ServerMode.HOT,
            ),
            "docker-enabled": McpServerConfig(
                name="docker-enabled",
                server_type=ServerType.DOCKER,
                command="custom",
                args=[],
                env={},
                enabled=True,
                mode=ServerMode.COLD,
            ),
        }

    def test_get_process_servers(self, sample_config):
        """Test filtering process-type servers."""
        result = get_process_servers(sample_config)

        assert len(result) == 3
        assert "process-hot" in result
        assert "process-cold" in result
        assert "process-disabled" in result
        assert "docker-enabled" not in result

    def test_get_docker_servers(self, sample_config):
        """Test filtering docker-type servers."""
        result = get_docker_servers(sample_config)

        assert len(result) == 1
        assert "docker-enabled" in result

    def test_get_enabled_servers(self, sample_config):
        """Test filtering enabled servers."""
        result = get_enabled_servers(sample_config)

        assert len(result) == 3
        assert "process-hot" in result
        assert "process-cold" in result
        assert "docker-enabled" in result
        assert "process-disabled" not in result

    def test_get_hot_servers(self, sample_config):
        """Test filtering HOT mode servers (enabled + hot)."""
        result = get_hot_servers(sample_config)

        assert len(result) == 1
        assert "process-hot" in result
        # Disabled hot server should not be included
        assert "process-disabled" not in result

    def test_get_cold_servers(self, sample_config):
        """Test filtering COLD mode servers (enabled + cold)."""
        result = get_cold_servers(sample_config)

        assert len(result) == 2
        assert "process-cold" in result
        assert "docker-enabled" in result


class TestServerModeEnum:
    """Test ServerMode enum values."""

    def test_hot_value(self):
        assert ServerMode.HOT.value == "hot"

    def test_cold_value(self):
        assert ServerMode.COLD.value == "cold"

    def test_from_string(self):
        assert ServerMode("hot") == ServerMode.HOT
        assert ServerMode("cold") == ServerMode.COLD


class TestServerTypeEnum:
    """Test ServerType enum values."""

    def test_process_value(self):
        assert ServerType.PROCESS.value == "process"

    def test_docker_value(self):
        assert ServerType.DOCKER.value == "docker"
