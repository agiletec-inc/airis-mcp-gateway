"""
MCP Config Loader - Parse mcp-config.json and classify servers.

Determines:
- process type: uvx, npx, node, python, deno (direct subprocess)
- docker type: servers that run via Docker MCP Gateway
"""

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .process_runner import ProcessConfig


class ServerType(Enum):
    PROCESS = "process"  # uvx, npx, node, python, deno
    DOCKER = "docker"    # Docker MCP Gateway


class ServerMode(Enum):
    HOT = "hot"    # Always ready, descriptions included
    COLD = "cold"  # Lazy loaded, descriptions on-demand


# Commands that indicate a process-based MCP server
PROCESS_COMMANDS = {
    "uvx",
    "npx",
    "node",
    "python",
    "python3",
    "deno",
    "bun",
    "sh",  # sh -c "docker run..." still uses StdIO JSON-RPC
}


@dataclass
class McpServerConfig:
    """Parsed MCP server configuration."""
    name: str
    server_type: ServerType
    command: str
    args: list[str]
    env: dict[str, str]
    enabled: bool
    mode: ServerMode = ServerMode.COLD  # Default to cold
    cwd: Optional[str] = None
    runner: Optional[str] = None  # "local" or "remote" for profile-based servers
    # TTL settings (optional, uses ProcessConfig defaults if not specified)
    idle_timeout: Optional[int] = None
    min_ttl: Optional[int] = None
    max_ttl: Optional[int] = None
    adaptive_ttl_enabled: Optional[bool] = None

    def to_process_config(self, idle_timeout: int = 120) -> ProcessConfig:
        """Convert to ProcessConfig for ProcessRunner."""
        config = ProcessConfig(
            name=self.name,
            command=self.command,
            args=self.args,
            env=self.env,
            cwd=self.cwd,
            idle_timeout=self.idle_timeout if self.idle_timeout is not None else idle_timeout,
        )
        # Override TTL settings if specified
        if self.min_ttl is not None:
            config.min_ttl = self.min_ttl
        if self.max_ttl is not None:
            config.max_ttl = self.max_ttl
        if self.adaptive_ttl_enabled is not None:
            config.adaptive_ttl_enabled = self.adaptive_ttl_enabled
        return config


def classify_server_type(command: str) -> ServerType:
    """
    Determine if a server is process-based or docker-based.

    Process commands: uvx, npx, node, python, deno, bun, sh
    Docker commands: everything else (handled by Docker MCP Gateway)
    """
    # Extract base command (handle paths like /usr/bin/node)
    base_cmd = Path(command).name if "/" in command else command

    if base_cmd in PROCESS_COMMANDS:
        return ServerType.PROCESS

    return ServerType.DOCKER


def load_mcp_config(config_path: Optional[str] = None) -> dict[str, McpServerConfig]:
    """
    Load and parse mcp-config.json.

    Args:
        config_path: Path to mcp-config.json. Defaults to:
            1. MCP_CONFIG_PATH env var
            2. /app/mcp-config.json (in container)
            3. ./mcp-config.json (development)

    Returns:
        Dict mapping server name to McpServerConfig
    """
    if config_path is None:
        config_path = os.getenv("MCP_CONFIG_PATH")

    if config_path is None:
        # Try common locations
        candidates = [
            "/app/mcp-config.json",
            "./mcp-config.json",
            "../mcp-config.json",
            "../../mcp-config.json",
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                config_path = candidate
                break

    if config_path is None or not os.path.exists(config_path):
        print("[McpConfigLoader] No mcp-config.json found, using empty config")
        return {}

    print(f"[McpConfigLoader] Loading config from: {config_path}")

    with open(config_path) as f:
        raw_config = json.load(f)

    servers: dict[str, McpServerConfig] = {}
    mcp_servers = raw_config.get("mcpServers", {})
    profiles = raw_config.get("profiles", {})

    for name, server_def in mcp_servers.items():
        env = server_def.get("env", {})
        enabled = server_def.get("enabled", False)
        mode_str = server_def.get("mode", "cold")

        # Check for profile-based configuration
        profile_ref = server_def.get("profile")
        if profile_ref:
            # Expand environment variables in profile reference (e.g., ${SERENA_MODE:-serena-remote})
            profile_name = _expand_env_vars(profile_ref)
            profile = profiles.get(profile_name, {})
            if not profile:
                print(f"[McpConfigLoader] Warning: profile '{profile_name}' not found for server '{name}'")
                continue
            command = profile.get("command", "")
            args = profile.get("args", [])
            runner = "local" if profile_name.endswith("-local") else "remote"
            print(f"[McpConfigLoader] {name}: using profile '{profile_name}' (runner={runner})")
        else:
            command = server_def.get("command", "")
            args = server_def.get("args", [])
            runner = None

        # Parse mode
        try:
            mode = ServerMode(mode_str)
        except ValueError:
            mode = ServerMode.COLD

        # Expand environment variables in args
        expanded_args = [_expand_env_vars(arg) for arg in args]

        # Expand environment variables in env values
        expanded_env = {k: _expand_env_vars(v) for k, v in env.items()}

        server_type = classify_server_type(command)

        # Parse TTL settings (optional)
        idle_timeout = server_def.get("idle_timeout")
        min_ttl = server_def.get("min_ttl")
        max_ttl = server_def.get("max_ttl")
        adaptive_ttl_enabled = server_def.get("adaptive_ttl_enabled")

        servers[name] = McpServerConfig(
            name=name,
            server_type=server_type,
            command=command,
            args=expanded_args,
            env=expanded_env,
            enabled=enabled,
            mode=mode,
            runner=runner,
            idle_timeout=idle_timeout,
            min_ttl=min_ttl,
            max_ttl=max_ttl,
            adaptive_ttl_enabled=adaptive_ttl_enabled,
        )

        print(f"[McpConfigLoader] {name}: type={server_type.value}, mode={mode.value}, enabled={enabled}")

    return servers


def _expand_env_vars(value: str) -> str:
    """Expand ${VAR} style environment variables."""
    if not isinstance(value, str):
        return value

    result = value
    # Handle ${VAR} and ${VAR:-default} patterns
    import re
    pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'

    def replacer(match):
        var_name = match.group(1)
        default = match.group(2) or ""
        return os.getenv(var_name, default)

    return re.sub(pattern, replacer, result)


def get_process_servers(config: dict[str, McpServerConfig]) -> dict[str, McpServerConfig]:
    """Filter to only process-type servers."""
    return {
        name: server
        for name, server in config.items()
        if server.server_type == ServerType.PROCESS
    }


def get_docker_servers(config: dict[str, McpServerConfig]) -> dict[str, McpServerConfig]:
    """Filter to only docker-type servers."""
    return {
        name: server
        for name, server in config.items()
        if server.server_type == ServerType.DOCKER
    }


def get_enabled_servers(config: dict[str, McpServerConfig]) -> dict[str, McpServerConfig]:
    """Filter to only enabled servers."""
    return {
        name: server
        for name, server in config.items()
        if server.enabled
    }


def get_hot_servers(config: dict[str, McpServerConfig]) -> dict[str, McpServerConfig]:
    """Filter to only HOT mode servers (enabled + hot)."""
    return {
        name: server
        for name, server in config.items()
        if server.enabled and server.mode == ServerMode.HOT
    }


def get_cold_servers(config: dict[str, McpServerConfig]) -> dict[str, McpServerConfig]:
    """Filter to only COLD mode servers (enabled + cold)."""
    return {
        name: server
        for name, server in config.items()
        if server.enabled and server.mode == ServerMode.COLD
    }
