"""Behavior Compiler — compiles mcp-config.json behavior specs into compact instructions.

Reads behavior definitions from server configs and produces a ~800 token
instructions string for the MCP initialize response. This enables proactive
tool usage by LLMs without per-tool definition files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .logging import get_logger
from .routing_engine import format_routing_table_as_instructions

if TYPE_CHECKING:
    from .mcp_config_loader import McpServerConfig

logger = get_logger(__name__)

# Priority sort order
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Base instructions (always included)
_BASE_INSTRUCTIONS = (
    "This is AIRIS MCP Gateway with Dynamic MCP. "
    "IMPORTANT: Do NOT call tools directly. Instead:\n"
    "1. Use 'airis-find' to search for tools by name/description\n"
    "2. Use 'airis-schema' to get the input schema for a tool\n"
    "3. Use 'airis-exec' to execute the tool\n"
    "All 60+ tools are accessed through these 3 meta-tools. "
    "This provides 98% token reduction while maintaining full functionality."
)

_META_TOOLS_SECTION = (
    "## Additional Meta-Tools\n"
    "- 'airis-confidence': Pre-implementation confidence check. Use before starting complex tasks.\n"
    "- 'airis-repo-index': Generate repository structure overview for unfamiliar codebases.\n"
    "- 'airis-suggest': Get tool recommendations from natural language intent.\n\n"
    "When you need a capability (web search, memory, code analysis, etc.), "
    "ALWAYS start with airis-find or airis-suggest to discover available tools."
)


def compile_instructions(server_configs: dict[str, McpServerConfig]) -> str:
    """Compile behavior specs from server configs into instructions string.

    Args:
        server_configs: Dict mapping server name to McpServerConfig

    Returns:
        Compiled instructions string for MCP initialize response
    """
    sections = [_BASE_INSTRUCTIONS, _META_TOOLS_SECTION]

    # Collect behaviors from all servers (including disabled — they can be auto-enabled)
    behavior_lines = _compile_behavior_lines(server_configs)
    if behavior_lines:
        sections.append("## Proactive Tool Usage\n" + "\n".join(behavior_lines))

    # Append routing table Quick Routes
    routing_instructions = format_routing_table_as_instructions()
    if routing_instructions:
        sections.append(routing_instructions)

    return "\n\n".join(sections)


def _compile_behavior_lines(
    server_configs: dict[str, McpServerConfig],
) -> list[str]:
    """Extract and sort behavior lines from server configs.

    Returns:
        List of "WHEN <trigger> -> <instruction> [server]" lines,
        sorted by priority (high > medium > low).
    """
    from .mcp_config_loader import ServerMode

    entries: list[tuple[int, str]] = []  # (priority_order, line)

    for name, config in server_configs.items():
        if config.behavior is None:
            continue

        behavior = config.behavior
        if not behavior.triggers or not behavior.instruction:
            continue

        priority_order = _PRIORITY_ORDER.get(behavior.priority, 1)

        # Determine tool reference format based on mode
        if config.enabled and config.mode == ServerMode.HOT:
            tool_ref = f"[{name}]"
        else:
            tool_ref = f"airis-exec {name}:* [{name}]"

        trigger_str = " / ".join(behavior.triggers)
        line = f"WHEN {trigger_str} \u2192 {behavior.instruction} {tool_ref}"
        entries.append((priority_order, line))

    # Sort by priority
    entries.sort(key=lambda x: x[0])

    return [line for _, line in entries]
