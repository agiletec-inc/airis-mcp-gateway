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

# Priority sort order
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Base instructions (always included) — standard 3-step mode
_BASE_INSTRUCTIONS = (
    "This is AIRIS MCP Gateway with Dynamic MCP. "
    "IMPORTANT: Do NOT call tools directly. Instead:\n"
    "1. Use 'airis-exec' to execute any tool — all available tool names are listed in its description\n"
    "2. If arguments are wrong, the schema will be returned automatically\n"
    "3. Before implementation, inspect the repo and check docs for unfamiliar libraries or APIs\n"
    "All 60+ tools are accessed through airis-exec. "
    "This provides 98% token reduction while maintaining full functionality."
)

# Base instructions for LLM Tool Selection mode — single-tool mode
_BASE_INSTRUCTIONS_LLM_SELECTION = (
    "This is AIRIS MCP Gateway with LLM Tool Selection. "
    "All tools are listed in the airis-exec description. "
    "Pick a tool by name and call airis-exec directly:\n"
    "  airis-exec tool=\"server:tool_name\" arguments={...}\n"
    "If you're unsure about arguments, call airis-exec with just the tool name "
    "and no arguments — it will return the schema."
)

_META_TOOLS_SECTION = (
    "## Additional Meta-Tools\n"
    "- 'airis-confidence': Pre-implementation confidence check. Use before starting complex tasks.\n"
    "- 'airis-repo-index': Generate repository structure overview for unfamiliar codebases.\n"
    "- 'airis-suggest': Get tool recommendations from natural language intent.\n\n"
    "When you need a capability, check airis-exec's description for available tools, "
    "or use airis-find to search by keyword."
)

_META_TOOLS_SECTION_LLM_SELECTION = (
    "## Additional Meta-Tools\n"
    "- 'airis-confidence': Pre-implementation confidence check. Use before starting complex tasks.\n"
    "- 'airis-repo-index': Generate repository structure overview for unfamiliar codebases."
)

_TOOL_ROUTING_GUIDE = (
    "## Tool Routing Guide\n"
    "Use Gateway (airis-exec) for API/service calls. Use host tools for everything else.\n\n"
    "Gateway (airis-exec): library docs → context7 | web search → tavily | "
    "database → supabase | payments → stripe | DNS/workers → cloudflare | design files → figma\n\n"
    "Host tools (NOT Gateway): browser automation → playwright-cli skill (needs host Chrome) | "
    "file generation (docx/xlsx/pdf) → claude-api plugin | "
    "TDD/debugging/planning → superpowers plugin | "
    "git operations → gh CLI or native git | "
    "simple code read/edit → native Read/Edit/Grep tools\n\n"
    "Rules: docs before code | API/service → Gateway | browser testing → Playwright CLI first | "
    "host-dependent → plugin/skill/CLI | simple file ops → native tools."
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
    from .config import settings

    if settings.LLM_TOOL_SELECTION:
        sections = [_BASE_INSTRUCTIONS_LLM_SELECTION, _META_TOOLS_SECTION_LLM_SELECTION, _TOOL_ROUTING_GUIDE]
        workflows = []
    else:
        workflows = load_workflows()

    # Use workflow texts if available, otherwise fall back to hardcoded constant
    workflow_text = _compile_workflow_texts(workflows)
    sections = [_BASE_INSTRUCTIONS, _META_TOOLS_SECTION, workflow_text or _TOOL_ROUTING_GUIDE]

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
    from .mcp_config_loader import ServerMode

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

        # Determine tool reference format based on mode
        if config.enabled and config.mode == ServerMode.HOT:
            tool_ref = f"[{name}]"
        else:
            tool_ref = f"airis-exec {name}:* [{name}]"

        trigger_str = " / ".join(behavior.triggers)
        line = f"WHEN {trigger_str} → {behavior.instruction} {tool_ref}"
        entries.append((priority_order, line))

    # Sort by priority
    entries.sort(key=lambda x: x[0])

    return [line for _, line in entries]
