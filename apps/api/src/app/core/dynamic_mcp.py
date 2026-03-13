"""
Dynamic MCP - Token-efficient tool discovery and execution.

Instead of exposing all tools in tools/list (which bloats context),
Dynamic MCP exposes only two meta-tools:
- airis-find: Search for tools/servers
- airis-exec: Execute any tool by name

This reduces context usage from O(n*tools) to O(1).
"""

import json
import re
from typing import Any, Optional
from dataclasses import dataclass, field

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolInfo:
    """Cached tool information for search."""
    name: str
    server: str
    description: str
    input_schema: dict = field(default_factory=dict)
    source: str = "process"  # "process" or "docker"


@dataclass
class ServerInfo:
    """Cached server information."""
    name: str
    enabled: bool
    mode: str  # "hot" or "cold"
    tools_count: int
    source: str = "process"


class DynamicMCP:
    """
    Dynamic MCP implementation for token-efficient tool access.

    Usage:
        dynamic_mcp = DynamicMCP()
        await dynamic_mcp.refresh_cache(process_manager, docker_tools)

        # Search tools
        results = dynamic_mcp.find(query="memory")

        # Execute tool
        result = await dynamic_mcp.exec("memory:create_entities", {...})
    """

    def __init__(self):
        self._tools: dict[str, ToolInfo] = {}  # tool_name -> ToolInfo
        self._servers: dict[str, ServerInfo] = {}  # server_name -> ServerInfo
        self._tool_to_server: dict[str, str] = {}  # tool_name -> server_name

    async def refresh_cache(
        self,
        process_manager,
        docker_tools: Optional[list[dict]] = None
    ):
        """
        Refresh the tool/server cache from all sources.

        Uses atomic update pattern to avoid race conditions during refresh.

        Args:
            process_manager: ProcessManager instance
            docker_tools: Tools from Docker MCP Gateway (optional)
        """
        # Build new cache in temporary variables (atomic update pattern)
        new_tools: dict[str, ToolInfo] = {}
        new_servers: dict[str, ServerInfo] = {}
        new_tool_to_server: dict[str, str] = {}

        # Cache process servers and their tools
        for name in process_manager.get_enabled_servers():
            status = process_manager.get_server_status(name)

            new_servers[name] = ServerInfo(
                name=name,
                enabled=status.get("enabled", False),
                mode=status.get("mode", "cold"),
                tools_count=status.get("tools_count", 0),
                source="process"
            )

            # Get tools for this server (lazy load)
            try:
                tools = await process_manager._list_tools_for_server(name)
                for tool in tools:
                    tool_name = tool.get("name", "")
                    if tool_name:
                        new_tools[tool_name] = ToolInfo(
                            name=tool_name,
                            server=name,
                            description=tool.get("description", ""),
                            input_schema=tool.get("inputSchema", {}),
                            source="process"
                        )
                        new_tool_to_server[tool_name] = name
            except Exception as e:
                logger.error(f"Failed to cache tools for {name}: {e}")

        # Cache Docker MCP Gateway tools
        docker_server_tools: dict[str, int] = {}  # server_name -> tools_count
        if docker_tools:
            for tool in docker_tools:
                tool_name = tool.get("name", "")
                if tool_name and tool_name not in new_tools:
                    # Try to infer server name from tool name
                    server_name = self._infer_server_name(tool_name)

                    new_tools[tool_name] = ToolInfo(
                        name=tool_name,
                        server=server_name,
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {}),
                        source="docker"
                    )
                    new_tool_to_server[tool_name] = server_name

                    # Count tools per Docker server
                    docker_server_tools[server_name] = docker_server_tools.get(server_name, 0) + 1

            # Add Docker servers to server cache
            for server_name, tools_count in docker_server_tools.items():
                if server_name not in new_servers:
                    new_servers[server_name] = ServerInfo(
                        name=server_name,
                        enabled=True,
                        mode="docker",  # Docker servers are always running
                        tools_count=tools_count,
                        source="docker"
                    )

        # Atomic swap - assign all at once to minimize window of inconsistency
        self._tools = new_tools
        self._servers = new_servers
        self._tool_to_server = new_tool_to_server

        logger.info(f"Cached {len(self._tools)} tools from {len(self._servers)} servers")

    async def refresh_cache_hot_only(
        self,
        process_manager,
        docker_tools: Optional[list[dict]] = None
    ):
        """
        Refresh cache with HOT servers only (fast, no cold server startup).

        Cold server tools will be loaded on-demand via airis-find.
        Uses atomic update to avoid race conditions.

        Args:
            process_manager: ProcessManager instance
            docker_tools: Tools from Docker MCP Gateway (optional)
        """
        # Build new cache in temporary variables (atomic update pattern)
        new_tools: dict[str, ToolInfo] = {}
        new_servers: dict[str, ServerInfo] = {}
        new_tool_to_server: dict[str, str] = {}

        # Cache ALL server info (but only HOT server tools)
        hot_servers = process_manager.get_hot_servers()
        for name in process_manager.get_enabled_servers():
            status = process_manager.get_server_status(name)
            is_hot = name in hot_servers

            new_servers[name] = ServerInfo(
                name=name,
                enabled=status.get("enabled", False),
                mode="hot" if is_hot else "cold",
                tools_count=status.get("tools_count", 0),
                source="process"
            )

            # Only get tools from HOT servers (already running)
            if is_hot:
                try:
                    tools = await process_manager._list_tools_for_server(name)
                    for tool in tools:
                        tool_name = tool.get("name", "")
                        if tool_name:
                            new_tools[tool_name] = ToolInfo(
                                name=tool_name,
                                server=name,
                                description=tool.get("description", ""),
                                input_schema=tool.get("inputSchema", {}),
                                source="process"
                            )
                            new_tool_to_server[tool_name] = name
                except Exception as e:
                    logger.error(f"Failed to cache HOT tools for {name}: {e}")

        # Cache Docker MCP Gateway tools
        docker_server_tools: dict[str, int] = {}
        if docker_tools:
            for tool in docker_tools:
                tool_name = tool.get("name", "")
                if tool_name and tool_name not in new_tools:
                    server_name = self._infer_server_name(tool_name)
                    new_tools[tool_name] = ToolInfo(
                        name=tool_name,
                        server=server_name,
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {}),
                        source="docker"
                    )
                    new_tool_to_server[tool_name] = server_name
                    docker_server_tools[server_name] = docker_server_tools.get(server_name, 0) + 1

            for server_name, tools_count in docker_server_tools.items():
                if server_name not in new_servers:
                    new_servers[server_name] = ServerInfo(
                        name=server_name,
                        enabled=True,
                        mode="docker",
                        tools_count=tools_count,
                        source="docker"
                    )

        # Atomic swap - replace all caches at once
        self._tools = new_tools
        self._servers = new_servers
        self._tool_to_server = new_tool_to_server

        logger.info(f"Cached {len(self._tools)} HOT tools from {len(self._servers)} servers (COLD tools on-demand)")

    async def load_tools_for_server(
        self,
        server_name: str,
        process_manager,
        force_enable: bool = False
    ) -> list[dict]:
        """
        Load tools for a specific server on-demand.

        This is used by airis-find to load tools for COLD/disabled servers
        when the LLM queries a specific server.

        Args:
            server_name: Server to load tools from
            process_manager: ProcessManager instance
            force_enable: If True, enable the server if disabled (for airis-exec)

        Returns:
            List of tool definitions
        """
        config = process_manager._server_configs.get(server_name)
        if not config:
            return []

        # Auto-enable if requested (for airis-exec)
        if force_enable and not config.enabled:
            await process_manager.enable_server(server_name)
            logger.info(f"Auto-enabled server: {server_name}")

        # Still disabled? Return empty
        if not config.enabled and not force_enable:
            return []

        # Load tools from the server
        try:
            tools = await process_manager._list_tools_for_server(server_name)

            # Cache the loaded tools
            for tool in tools:
                tool_name = tool.get("name", "")
                if tool_name and tool_name not in self._tools:
                    self._tools[tool_name] = ToolInfo(
                        name=tool_name,
                        server=server_name,
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {}),
                        source="process"
                    )
                    self._tool_to_server[tool_name] = server_name

            # Update server tools count
            if server_name in self._servers:
                self._servers[server_name].tools_count = len(tools)

            logger.debug(f"Loaded {len(tools)} tools from {server_name}")
            return tools
        except Exception as e:
            logger.error(f"Failed to load tools from {server_name}: {e}")
            return []

    def _infer_server_name(self, tool_name: str) -> str:
        """Infer server name from tool name pattern."""
        # Known Docker server tool prefixes mapping
        # mindbase tools: conversation_, session_, memory_
        docker_tool_prefixes = {
            "conversation_": "mindbase",
            "session_": "mindbase",
            "memory_": "mindbase",
            "get_current_time": "time",
            "convert_time": "time",
        }

        # Check known prefixes first
        for prefix, server in docker_tool_prefixes.items():
            if tool_name.startswith(prefix) or tool_name == prefix.rstrip("_"):
                return server

        # Common patterns: server_action, serverAction
        if "_" in tool_name:
            return tool_name.split("_")[0]

        # CamelCase: getMemory -> get (not useful), so return "docker"
        return "docker"

    def find(
        self,
        query: Optional[str] = None,
        server: Optional[str] = None,
        limit: int = 20
    ) -> dict[str, Any]:
        """
        Search for tools and servers.

        Args:
            query: Search query (matches tool name, description, server name)
            server: Filter by server name
            limit: Max results to return

        Returns:
            Dict with matched servers and tools
        """
        matched_tools = []
        matched_servers = []

        query_lower = query.lower() if query else None

        # Search servers
        for name, info in self._servers.items():
            if server and name != server:
                continue

            if query_lower and query_lower not in name.lower():
                continue

            matched_servers.append({
                "name": info.name,
                "enabled": info.enabled,
                "mode": info.mode,
                "tools_count": info.tools_count,
            })

        # Search tools
        for name, info in self._tools.items():
            if server and info.server != server:
                continue

            if query_lower:
                # Match against name, description, or server
                if not (
                    query_lower in name.lower() or
                    query_lower in info.description.lower() or
                    query_lower in info.server.lower()
                ):
                    continue

            matched_tools.append({
                "name": info.name,
                "server": info.server,
                "description": self._truncate(info.description, 100),
            })

            if len(matched_tools) >= limit:
                break

        return {
            "servers": matched_servers[:limit],
            "tools": matched_tools,
            "total_servers": len(self._servers),
            "total_tools": len(self._tools),
        }

    def get_tool_schema(self, tool_name: str) -> Optional[dict]:
        """Get full schema for a specific tool."""
        info = self._tools.get(tool_name)
        if not info:
            return None

        return {
            "name": info.name,
            "server": info.server,
            "description": info.description,
            "inputSchema": info.input_schema,
        }

    def get_server_for_tool(self, tool_name: str) -> Optional[str]:
        """Get server name for a tool."""
        return self._tool_to_server.get(tool_name)

    def parse_tool_reference(self, tool_ref: str) -> tuple[Optional[str], str]:
        """
        Parse tool reference like "server:tool" or just "tool".

        Returns:
            (server_name, tool_name) - server_name may be None
        """
        if ":" in tool_ref:
            parts = tool_ref.split(":", 1)
            return parts[0], parts[1]

        # No server specified, try to find it
        server = self._tool_to_server.get(tool_ref)
        return server, tool_ref

    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text to max length."""
        if not text or len(text) <= max_length:
            return text
        return text[:max_length - 1] + "…"

    def get_meta_tools(self) -> list[dict]:
        """
        Get the meta-tools for Dynamic MCP mode.

        Returns:
            List of tool definitions for airis-find, airis-exec, airis-schema,
            airis-confidence, airis-repo-index, and airis-suggest
        """
        return [
            {
                "name": "airis-find",
                "description": "Search for available MCP tools and servers. Use this to discover what tools are available before calling airis-exec.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to match against tool names, descriptions, or server names. Examples: 'memory', 'file', 'browser'"
                        },
                        "server": {
                            "type": "string",
                            "description": "Filter results to a specific server name"
                        }
                    }
                }
            },
            {
                "name": "airis-exec",
                "description": "Execute any MCP tool by name. First use airis-find to discover available tools, then use this to execute them.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": "Tool name to execute. Can be 'tool_name' or 'server:tool_name' format. Use airis-find first to discover tool names."
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments to pass to the tool. Use airis-find with the tool name to see required arguments."
                        }
                    },
                    "required": ["tool"]
                }
            },
            {
                "name": "airis-schema",
                "description": "Get the full input schema for a specific tool. Use this before airis-exec to see required arguments.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": "Tool name to get schema for"
                        }
                    },
                    "required": ["tool"]
                }
            },
            {
                "name": "airis-confidence",
                "description": "Pre-implementation confidence check. Assess confidence level before starting implementation to prevent wrong-direction execution. Returns score (0-1), verdict (proceed/present_alternatives/ask_user/stop), and clarifying questions if needed.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Description of the implementation task"
                        },
                        "has_official_docs": {
                            "type": "boolean",
                            "description": "Official documentation has been reviewed (+0.2)"
                        },
                        "has_existing_patterns": {
                            "type": "boolean",
                            "description": "Existing codebase patterns identified (+0.2)"
                        },
                        "has_clear_path": {
                            "type": "boolean",
                            "description": "Clear implementation path exists (+0.2)"
                        },
                        "multiple_approaches": {
                            "type": "boolean",
                            "description": "Multiple viable approaches exist (-0.1)"
                        },
                        "has_trade_offs": {
                            "type": "boolean",
                            "description": "Trade-offs require consideration (-0.1)"
                        },
                        "unclear_requirements": {
                            "type": "boolean",
                            "description": "Requirements are vague or incomplete (-0.2)"
                        },
                        "no_precedent": {
                            "type": "boolean",
                            "description": "No similar implementations to reference (-0.2)"
                        },
                        "missing_domain_knowledge": {
                            "type": "boolean",
                            "description": "Domain expertise is lacking (-0.2)"
                        }
                    }
                }
            },
            {
                "name": "airis-repo-index",
                "description": "Generate a repository index with structure overview, entry points, documentation, and configuration files. Useful for understanding unfamiliar codebases.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "Path to the repository to index (absolute or relative)"
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["full", "update", "quick"],
                            "description": "Indexing mode: 'full' (deep, 6 levels), 'update' (medium, 4 levels), 'quick' (shallow, 2 levels)"
                        },
                        "include_docs": {
                            "type": "boolean",
                            "description": "Include documentation files (default: true)"
                        },
                        "include_tests": {
                            "type": "boolean",
                            "description": "Include test directories (default: true)"
                        },
                        "max_entries": {
                            "type": "integer",
                            "description": "Maximum top-level entries to include (default: 10)"
                        }
                    },
                    "required": ["repo_path"]
                }
            },
            {
                "name": "airis-suggest",
                "description": "Suggest appropriate MCP tools based on natural language intent. Analyzes your intent and returns ranked tool suggestions with match scores.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "description": "Natural language description of what you want to do. Examples: 'create invoice with stripe', 'search for files containing error', 'navigate to a webpage'"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of suggestions to return (default: 5)"
                        }
                    },
                    "required": ["intent"]
                }
            },
            {
                "name": "airis-route",
                "description": "Route a task to the optimal tool chain. Matches task against known patterns and returns the recommended tool execution order. Faster than airis-find for common workflows.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Natural language task description. Examples: 'research best practices for React hooks', 'query user table in database', 'create a Stripe invoice'"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of additional suggestions to return (default: 5)"
                        }
                    },
                    "required": ["task"]
                }
            }
        ]


# Global singleton
_dynamic_mcp: Optional[DynamicMCP] = None


def get_dynamic_mcp() -> DynamicMCP:
    """Get the global DynamicMCP instance."""
    global _dynamic_mcp
    if _dynamic_mcp is None:
        _dynamic_mcp = DynamicMCP()
    return _dynamic_mcp
