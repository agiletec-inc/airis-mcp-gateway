"""
Dynamic MCP - Token-efficient tool discovery and activation.
"""

from typing import Any, Optional
from dataclasses import dataclass, field

from .logging import get_logger
from .mcp_config_loader import is_discoverable
from .toolset_catalog import ToolsetInfo, build_toolset_index

logger = get_logger(__name__)


@dataclass
class ToolInfo:
    """Cached tool information for search."""

    name: str
    server: str
    description: str
    input_schema: dict = field(default_factory=dict)
    source: str = "process"  # "process", "docker", or "index"


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
        self._toolsets: dict[str, ToolsetInfo] = {}  # toolset_ref -> ToolsetInfo
        self._tool_to_toolsets: dict[str, set[str]] = {}  # tool_name -> toolset refs

    async def refresh_cache(
        self, process_manager, docker_tools: Optional[list[dict]] = None
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
                source="process",
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
                            source="process",
                        )
                        new_tool_to_server[tool_name] = name
            except Exception as e:
                logger.error(f"Failed to cache tools for {name}: {e}")
                process_manager.record_health(name, "list_failed", str(e))

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
                        source="docker",
                    )
                    new_tool_to_server[tool_name] = server_name

                    # Count tools per Docker server
                    docker_server_tools[server_name] = (
                        docker_server_tools.get(server_name, 0) + 1
                    )

            # Add Docker servers to server cache
            for server_name, tools_count in docker_server_tools.items():
                if server_name not in new_servers:
                    new_servers[server_name] = ServerInfo(
                        name=server_name,
                        enabled=True,
                        mode="docker",  # Docker servers are always running
                        tools_count=tools_count,
                        source="docker",
                    )

        # Atomic swap - assign all at once to minimize window of inconsistency
        self._tools = new_tools
        self._servers = new_servers
        self._tool_to_server = new_tool_to_server
        self.refresh_toolsets(process_manager)

        logger.info(
            f"Cached {len(self._tools)} tools from {len(self._servers)} servers"
        )

    async def refresh_cache_hot_only(
        self, process_manager, docker_tools: Optional[list[dict]] = None
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
                source="process",
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
                                source="process",
                            )
                            new_tool_to_server[tool_name] = name
                except Exception as e:
                    logger.error(f"Failed to cache HOT tools for {name}: {e}")
                    process_manager.record_health(name, "list_failed", str(e))

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
                        source="docker",
                    )
                    new_tool_to_server[tool_name] = server_name
                    docker_server_tools[server_name] = (
                        docker_server_tools.get(server_name, 0) + 1
                    )

            for server_name, tools_count in docker_server_tools.items():
                if server_name not in new_servers:
                    new_servers[server_name] = ServerInfo(
                        name=server_name,
                        enabled=True,
                        mode="docker",
                        tools_count=tools_count,
                        source="docker",
                    )

        # Cache tools_index from ALL discoverable servers (including COLD
        # and disabled-but-not-policy-disabled, e.g. stripe). This enables
        # discovery without starting servers. Only policy_disabled servers
        # (e.g. supabase, mindbase) are excluded — see is_discoverable().
        index_count = 0
        for name in process_manager.get_server_names():
            config = process_manager._server_configs.get(name)
            if config and is_discoverable(config) and config.tools_index:
                for tool_entry in config.tools_index:
                    tool_name = tool_entry.get("name", "")
                    if tool_name and tool_name not in new_tools:
                        new_tools[tool_name] = ToolInfo(
                            name=tool_name,
                            server=name,
                            description=tool_entry.get("description", ""),
                            input_schema={},
                            source="index",
                        )
                        new_tool_to_server[tool_name] = name
                        index_count += 1

        # Atomic swap - replace all caches at once
        self._tools = new_tools
        self._servers = new_servers
        self._tool_to_server = new_tool_to_server
        self.refresh_toolsets(process_manager)

        logger.info(
            f"Cached {len(self._tools)} tools ({index_count} from index) from {len(self._servers)} servers (COLD tools on-demand)"
        )

    def refresh_toolsets(self, process_manager) -> None:
        """Refresh logical toolset catalog from server configs."""
        self._toolsets = build_toolset_index(process_manager._server_configs)
        self._tool_to_toolsets = {}
        for ref, info in self._toolsets.items():
            for tool_name in info.tools:
                self._tool_to_toolsets.setdefault(tool_name, set()).add(ref)

    def build_tool_listing(
        self,
        excluded_servers: set[str] | None = None,
        hot_exposed_tools: set[str] | None = None,
        process_manager=None,
        compact: bool = False,
        compact_limit: int = 3,
    ) -> str:
        """Build compact tool listing grouped by server for airis-exec description.

        Args:
            compact: If True, show only top N tools per server with "+M" suffix.
            compact_limit: Number of tools to show per server in compact mode.

        Returns format like:
            Full:    [memory] create_entities, search_nodes, add_observations, delete_entities, ...
            Compact: [memory] create_entities, search_nodes, add_observations +4
        """
        excluded = excluded_servers or set()
        hot_tools = hot_exposed_tools or set()

        # Group tools by server from cache
        server_tools: dict[str, list[str]] = {}
        for tool_name, tool_info in self._tools.items():
            if tool_info.server in excluded:
                continue
            if tool_name in hot_tools:
                continue
            server_tools.setdefault(tool_info.server, []).append(tool_name)

        # Fallback: if cache is empty, read tools_index from process_manager configs
        if not server_tools and process_manager:
            for name in process_manager.get_server_names():
                if name in excluded:
                    continue
                config = process_manager._server_configs.get(name)
                if config and is_discoverable(config) and config.tools_index:
                    tools = [
                        t.get("name")
                        for t in config.tools_index
                        if t.get("name") and t.get("name") not in hot_tools
                    ]
                    if tools:
                        server_tools[name] = tools

        lines = []
        for server_name in sorted(server_tools.keys()):
            tools = sorted(server_tools[server_name])
            if compact and len(tools) > compact_limit:
                shown = ", ".join(tools[:compact_limit])
                remaining = len(tools) - compact_limit
                lines.append(f"[{server_name}] {shown} +{remaining}")
            else:
                lines.append(f"[{server_name}] {', '.join(tools)}")

        return "\n".join(lines)

    async def load_tools_for_server(
        self, server_name: str, process_manager, force_enable: bool = False
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

            # Cache the loaded tools (overwrite index entries with live data)
            for tool in tools:
                tool_name = tool.get("name", "")
                existing = self._tools.get(tool_name)
                if tool_name and (not existing or existing.source == "index"):
                    self._tools[tool_name] = ToolInfo(
                        name=tool_name,
                        server=server_name,
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {}),
                        source="process",
                    )
                    self._tool_to_server[tool_name] = server_name

            # Update server tools count
            if server_name in self._servers:
                self._servers[server_name].tools_count = len(tools)

            logger.debug(f"Loaded {len(tools)} tools from {server_name}")
            return tools
        except Exception as e:
            logger.error(f"Failed to load tools from {server_name}: {e}")
            process_manager.record_health(server_name, "list_failed", str(e))
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
        limit: int = 20,
        process_manager=None,
    ) -> dict[str, Any]:
        """
        Search for tools and servers.

        Args:
            query: Search query (matches tool name, description, server name)
            server: Filter by server name
            limit: Max results to return
            process_manager: If given, matched tools whose server is in a
                failure health state get a "server_status"/"server_error"
                annotation so the caller sees "found but currently broken"
                instead of the tool silently vanishing.

        Returns:
            Dict with matched servers and tools
        """
        matched_tools = []
        matched_servers = []
        matched_toolsets = []

        query_lower = query.lower() if query else None

        # Build query variants for flexible matching
        query_variants = []
        if query_lower:
            query_variants.append(query_lower)
            # "sequential thinking" -> "sequential-thinking", "sequential_thinking"
            query_variants.append(query_lower.replace(" ", "-"))
            query_variants.append(query_lower.replace(" ", "_"))
            # "sequential-thinking" -> "sequentialthinking"
            query_variants.append(
                query_lower.replace("-", "").replace("_", "").replace(" ", "")
            )
            # Deduplicate while preserving order
            query_variants = list(dict.fromkeys(query_variants))

        # Per-word keyword set for matching cached tools against TOOL_CATALOG.
        # Substring matching on the full query misses keyword-style queries
        # (e.g. "search past conversations" never substrings "conversation_search"),
        # so cached tools also match when their catalog keywords intersect.
        from .tool_suggester import TOOL_CATALOG, _extract_keywords

        query_keywords = set(_extract_keywords(query)) if query_lower else set()

        # Search servers
        for name, info in self._servers.items():
            if server and name != server:
                continue

            if query_variants:
                if not any(v in name.lower() for v in query_variants):
                    continue

            matched_servers.append(
                {
                    "name": info.name,
                    "enabled": info.enabled,
                    "mode": info.mode,
                    "tools_count": info.tools_count,
                }
            )

        # Search toolsets
        for ref, info in self._toolsets.items():
            if server and info.server != server:
                continue
            if query_variants:
                haystacks = (
                    ref.lower(),
                    info.summary.lower(),
                    info.server.lower(),
                    info.name.lower(),
                )
                if not any(any(v in hay for hay in haystacks) for v in query_variants):
                    continue
            matched_toolsets.append(
                {
                    "ref": ref,
                    "server": info.server,
                    "summary": info.summary,
                    "tools_count": len(info.tools),
                }
            )

        # Search tools
        for name, info in self._tools.items():
            if server and info.server != server:
                continue

            if query_variants:
                name_lower = name.lower()
                desc_lower = info.description.lower()
                server_lower = info.server.lower()
                substring_match = any(
                    v in name_lower or v in desc_lower or v in server_lower
                    for v in query_variants
                )
                catalog_keywords = TOOL_CATALOG.get(info.server, {}).get(name, [])
                keyword_match = bool(query_keywords & set(catalog_keywords))
                if not (substring_match or keyword_match):
                    continue

            tool_result = {
                "name": info.name,
                "server": info.server,
                "description": self._truncate(info.description, 100),
            }
            if process_manager is not None:
                health = process_manager.get_server_health(info.server)
                if health.status not in ("ok", "not_started"):
                    tool_result["server_status"] = health.status
                    if health.last_error:
                        tool_result["server_error"] = self._truncate(
                            health.last_error, 200
                        )
            matched_tools.append(tool_result)

            if len(matched_tools) >= limit:
                break

        # Fallback: search TOOL_CATALOG for tools not yet in cache
        if not matched_tools and query_lower:
            from .tool_suggester import TOOL_CATALOG, _extract_keywords

            query_keywords = set(_extract_keywords(query))
            if query_keywords:
                for server_name, tools in TOOL_CATALOG.items():
                    if server and server_name != server:
                        continue
                    for tool_name, keywords in tools.items():
                        # Skip tools already in cache
                        if tool_name in self._tools:
                            continue
                        if query_keywords & set(keywords):
                            matched_tools.append(
                                {
                                    "name": tool_name,
                                    "server": server_name,
                                    "description": f"[catalog] Keywords: {', '.join(keywords[:5])}",
                                }
                            )

                if matched_tools:
                    matched_tools = matched_tools[:limit]

        return {
            "servers": matched_servers[:limit],
            "toolsets": matched_toolsets[:limit],
            "tools": matched_tools,
            "total_servers": len(self._servers),
            "total_tools": len(self._tools),
        }

    def get_tool_schema(self, tool_name: str) -> Optional[dict]:
        """Get full schema for a specific tool.

        Returns None for index-sourced tools (no real schema available)
        to trigger auto-discovery and server startup.
        """
        info = self._tools.get(tool_name)
        if not info:
            return None

        # Index-sourced tools have no real schema - return None to trigger auto-discovery
        if info.source == "index":
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

    def get_server_for_tool_from_index(
        self, tool_name: str, process_manager
    ) -> Optional[str]:
        """
        Look up server name from tools_index in mcp-config.json.
        Used for auto-discovery when tool is not in cache.

        Discoverable (non policy_disabled) servers are matched first, so a
        bare tool name resolves to the same server the exposure collector
        advertised it under whenever a discoverable candidate exists (see
        is_discoverable / issue #198) — this is what fixes 'query' (indexed
        by both policy-disabled supabase and discoverable postgres)
        resolving to supabase instead of the advertised postgres.

        Non-discoverable servers are only used as a fallback when no
        discoverable server indexes the name, so a bare call for a tool that
        exists *solely* on a policy-disabled server still resolves to it and
        gets the explicit -32001 policy-disabled refusal in
        auto_discover_and_execute (rather than a generic "not found"),
        matching explicit `server:tool` addressing which bypasses this
        resolver entirely and always hits that refusal.
        """
        fallback: Optional[str] = None
        for name in process_manager.get_server_names():
            config = process_manager._server_configs.get(name)
            if not config or not config.tools_index:
                continue
            for tool_entry in config.tools_index:
                if tool_entry.get("name") == tool_name:
                    if is_discoverable(config):
                        return name
                    if fallback is None:
                        fallback = name
                    break
        return fallback

    async def auto_discover_and_execute(
        self, tool_name: str, arguments: dict, process_manager
    ) -> dict | None:
        """
        Auto-discover a COLD tool via tools_index, enable its server, and execute.

        Returns the result dict on success, or None if the tool can't be
        auto-discovered (not in any tools_index, or not a process server).
        """
        from .mcp_config_loader import ServerMode

        server_name = self.get_server_for_tool_from_index(tool_name, process_manager)
        if not server_name or not process_manager.is_process_server(server_name):
            return None

        logger.info(
            f"Auto-discovered COLD tool '{tool_name}' on server '{server_name}'"
        )

        config = process_manager._server_configs.get(server_name)
        if config and getattr(config, "policy_disabled", False):
            logger.warning(
                f"Refused auto-enable of policy-disabled server: {server_name}"
            )
            return {
                "error": {
                    "code": -32001,
                    "message": f"server '{server_name}' is policy-disabled and cannot be auto-enabled",
                }
            }

        if config and config.mode == ServerMode.COLD and not config.enabled:
            logger.info(f"Auto-enabling COLD server: {server_name}")
            await process_manager.enable_server(server_name)

        await self.load_tools_for_server(
            server_name, process_manager, force_enable=True
        )
        return await process_manager.call_tool_on_server(
            server_name, tool_name, arguments
        )

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
        return text[: max_length - 1] + "…"

    def get_meta_tools(self, mode: str = "core") -> list[dict]:
        """
        Get the meta-tools for Dynamic MCP mode.

        Returns:
            List of tool definitions.
        """
        # Core meta-tools (always included)
        tools = [
            {
                "name": "airis-find",
                "description": (
                    "Discover MCP tools and servers. Call with NO arguments for a "
                    "full inventory of every connected server (hot/cold/docker, "
                    "enabled status, tool counts) plus toolsets. Pass "
                    'server="<name>" to drill into one server\'s tools, or '
                    'query="keywords" to search tools across all servers.'
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keywords to search tools across all servers",
                        },
                        "server": {
                            "type": "string",
                            "description": "Server name to list that server's tools",
                        },
                    },
                },
            },
            {
                "name": "airis-schema",
                "description": "Get the full input schema for a specific native MCP tool. Use when you need to check required arguments before calling it directly.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": "Tool name to get schema for",
                        }
                    },
                    "required": ["tool"],
                },
            },
            {
                "name": "airis-workflow",
                "description": (
                    "Get the safe step-by-step procedure for a kind of task BEFORE acting. "
                    "Use when you are about to query or modify a database, debug an issue "
                    "involving external services or APIs, implement a feature with an "
                    "unfamiliar library/API, or research a library/API."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "enum": [
                                "database",
                                "debugging",
                                "implementation",
                                "research",
                            ],
                            "description": "The kind of task you are about to start",
                        }
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "airis-exec",
                "description": (
                    "Execute any MCP tool, including COLD-server tools that are not "
                    "shown in tools/list (supabase:query, stripe:*, twilio:*, figma:*, "
                    "tavily:* …). The COLD server is auto-enabled on first call. "
                    "Discover tool names with airis-find; get a tool's argument schema "
                    "with airis-schema. tools/list-only clients (Claude Code, Codex) "
                    "MUST use this to reach COLD tools."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": (
                                "Tool reference: 'server:tool' (e.g. 'supabase:query') "
                                "or a bare tool name (server auto-discovered)."
                            ),
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments for the target tool (see airis-schema).",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["tool"],
                },
            },
        ]

        # Extended meta-tools (only in "full" mode)
        if mode == "full":
            tools.extend(
                [
                    {
                        "name": "airis-confidence",
                        "description": "Pre-implementation confidence check. Assess confidence level before starting implementation to prevent wrong-direction execution. Returns score (0-1), verdict (proceed/present_alternatives/ask_user/stop), and clarifying questions if needed.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "task": {
                                    "type": "string",
                                    "description": "Description of the implementation task",
                                },
                                "has_official_docs": {
                                    "type": "boolean",
                                    "description": "Official documentation has been reviewed (+0.2)",
                                },
                                "has_existing_patterns": {
                                    "type": "boolean",
                                    "description": "Existing codebase patterns identified (+0.2)",
                                },
                                "has_clear_path": {
                                    "type": "boolean",
                                    "description": "Clear implementation path exists (+0.2)",
                                },
                                "multiple_approaches": {
                                    "type": "boolean",
                                    "description": "Multiple viable approaches exist (-0.1)",
                                },
                                "has_trade_offs": {
                                    "type": "boolean",
                                    "description": "Trade-offs require consideration (-0.1)",
                                },
                                "unclear_requirements": {
                                    "type": "boolean",
                                    "description": "Requirements are vague or incomplete (-0.2)",
                                },
                                "no_precedent": {
                                    "type": "boolean",
                                    "description": "No similar implementations to reference (-0.2)",
                                },
                                "missing_domain_knowledge": {
                                    "type": "boolean",
                                    "description": "Domain expertise is lacking (-0.2)",
                                },
                            },
                        },
                    },
                    {
                        "name": "airis-repo-index",
                        "description": "Generate a repository index with structure overview, entry points, documentation, and configuration files. Useful for understanding unfamiliar codebases.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "repo_path": {
                                    "type": "string",
                                    "description": "Path to the repository to index (absolute or relative)",
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["full", "update", "quick"],
                                    "description": "Indexing mode: 'full' (deep, 6 levels), 'update' (medium, 4 levels), 'quick' (shallow, 2 levels)",
                                },
                                "include_docs": {
                                    "type": "boolean",
                                    "description": "Include documentation files (default: true)",
                                },
                                "include_tests": {
                                    "type": "boolean",
                                    "description": "Include test directories (default: true)",
                                },
                                "max_entries": {
                                    "type": "integer",
                                    "description": "Maximum top-level entries to include (default: 10)",
                                },
                            },
                            "required": ["repo_path"],
                        },
                    },
                    {
                        "name": "airis-suggest",
                        "description": "Suggest appropriate MCP tools based on natural language intent. Analyzes your intent and returns ranked tool suggestions with match scores.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "intent": {
                                    "type": "string",
                                    "description": "Natural language description of what you want to do. Examples: 'create invoice with stripe', 'search for files containing error', 'navigate to a webpage'",
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Maximum number of suggestions to return (default: 5)",
                                },
                            },
                            "required": ["intent"],
                        },
                    },
                    {
                        "name": "airis-route",
                        "description": "Route a task to the optimal tool chain. Matches task against known patterns and returns the recommended tool execution order. Faster than airis-find for common workflows.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "task": {
                                    "type": "string",
                                    "description": "Natural language task description. Examples: 'research best practices for React hooks', 'query user table in database', 'create a Stripe invoice'",
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Maximum number of additional suggestions to return (default: 5)",
                                },
                            },
                            "required": ["task"],
                        },
                    },
                ]
            )

        return tools


# Global singleton
_dynamic_mcp: Optional[DynamicMCP] = None


def get_dynamic_mcp() -> DynamicMCP:
    """Get the global DynamicMCP instance."""
    global _dynamic_mcp
    if _dynamic_mcp is None:
        _dynamic_mcp = DynamicMCP()
    return _dynamic_mcp


def inject_schema_on_validation_error(error: Optional[dict], tool_name: str) -> None:
    """Re-hydrate an MCP validation error with the tool's full input schema.

    Under SCHEMA_MODE=lazy every tool's inputSchema is stubbed to {"type":
    "object"} to save context, so a client that calls a tool blind gets a
    -32602/-32000 back from the backend. Appending the real schema lets the
    caller self-heal on retry without a separate airis-schema round-trip.

    Mutates `error` in place. No-op for other error codes or unknown tools.
    """
    if not error or error.get("code") not in (-32602, -32000):
        return
    schema_info = get_dynamic_mcp().get_tool_schema(tool_name)
    input_schema = schema_info.get("inputSchema") if schema_info else None
    if input_schema:
        error["message"] += f"\n\nFull Schema: {input_schema}"
        error["hint"] = "Retry with the full schema provided above."
