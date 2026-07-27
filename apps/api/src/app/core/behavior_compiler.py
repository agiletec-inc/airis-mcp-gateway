"""Behavior Compiler — compiles workflows and behaviors into MCP instructions.

Reads workflow YAML recipes and server behavior configs, then produces
a ~1500 token instructions string for the MCP initialize response.
Workflows are directives (not suggestions) that force LLMs to use
the right MCP tools at the right time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .logging import get_logger
from .routing_engine import format_routing_table_as_instructions
from .workflow_loader import PRIORITY_ORDER, WorkflowConfig, load_workflows

if TYPE_CHECKING:
    from .mcp_config_loader import McpServerConfig

logger = get_logger(__name__)

# Base instructions (always included)
_BASE_INSTRUCTIONS = (
    "AIRIS MCP Gateway. Call MCP tools directly by name. "
    "Use airis-find to search for tools. "
    "Use airis-schema to inspect a tool's input schema before calling it when unsure."
)

_META_TOOLS_SECTION = (
    "## Available Service\n"
    "Use context7 only when exact current library or framework documentation is needed. "
    "Resolve the library ID, then query its documentation."
)

_TOOL_ROUTING_GUIDE = (
    "Use host tools for all work except exact current library or framework "
    "documentation, which may use context7."
)


def compile_instructions(server_configs: dict[str, McpServerConfig]) -> str:
    """Compile workflows and behavior specs into instructions string.

    Workflows take priority over behavior configs. Servers covered by
    workflows are excluded from the behavior lines section.

    Args:
        server_configs: Dict mapping server name to McpServerConfig

    Returns:
        Compiled instructions string for MCP initialize response
    """
    workflows = load_workflows()

    # Use workflow texts if available, otherwise fall back to hardcoded constant
    workflow_text = _compile_workflow_texts(workflows)
    sections = [
        _BASE_INSTRUCTIONS,
        _META_TOOLS_SECTION,
        workflow_text or _TOOL_ROUTING_GUIDE,
    ]

    # Servers covered by workflows are excluded from behavior lines
    workflow_servers = set()
    for wf in workflows:
        workflow_servers.update(wf.servers)

    behavior_lines = _compile_behavior_lines(server_configs, exclude=workflow_servers)
    if behavior_lines:
        sections.append("## Proactive Tool Usage\n" + "\n".join(behavior_lines))

    # Append routing table Quick Routes
    routing_instructions = format_routing_table_as_instructions()
    if routing_instructions:
        sections.append(routing_instructions)

    return "\n\n".join(sections)


def _compile_workflow_texts(workflows: list[WorkflowConfig]) -> str:
    """Compile workflow confirmed texts into a single string.

    Filters for compile_to: mcp_instructions, joins in priority order.
    Text is emitted verbatim — no template engine or variable expansion.

    Returns:
        Compiled text, or empty string if no matching workflows.
    """
    texts = []
    for wf in workflows:
        if wf.compile_to == "mcp_instructions" and wf.text.strip():
            texts.append(wf.text.strip())

    return "\n\n".join(texts)


def _compile_behavior_lines(
    server_configs: dict[str, McpServerConfig],
    exclude: set[str] | None = None,
) -> list[str]:
    """Extract and sort behavior lines from server configs.

    Args:
        server_configs: Server configurations with behavior definitions.
        exclude: Server names to skip (covered by workflow directives).

    Returns:
        List of "WHEN <trigger> -> <instruction> [server]" lines,
        sorted by priority (high > medium > low).
    """

    if exclude is None:
        exclude = set()

    entries: list[tuple[int, str]] = []  # (priority_order, line)

    for name, config in server_configs.items():
        if name in exclude:
            continue

        if config.behavior is None:
            continue

        behavior = config.behavior
        if not behavior.triggers or not behavior.instruction:
            continue

        priority_order = PRIORITY_ORDER.get(behavior.priority, 1)

        # COLD servers are now auto-started on first native tool call.
        # No need to instruct the LLM to use a router — call tools by name.
        tool_ref = f"[{name}]"

        trigger_str = " / ".join(behavior.triggers)
        line = f"WHEN {trigger_str} → {behavior.instruction} {tool_ref}"
        entries.append((priority_order, line))

    # Sort by priority
    entries.sort(key=lambda x: x[0])

    return [line for _, line in entries]
