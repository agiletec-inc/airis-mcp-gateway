"""Workflow Loader — loads workflow YAML files as confirmed-text directives.

Reads workflow definitions from workflows/ directory. Each YAML file contains
human-written confirmed text that is output verbatim into MCP instructions.
No template engine or variable expansion — what you write is what gets emitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .logging import get_logger

logger = get_logger(__name__)

_PRIORITY_VALUES = {"high", "medium", "low"}
_KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

# Priority sort order (shared with behavior_compiler)
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class WorkflowConfig:
    """Parsed workflow configuration.

    Attributes:
        name: Kebab-case identifier for the workflow.
        compile_to: Target for compilation (e.g., "mcp_instructions").
        priority: Importance level — high/medium/low.
        text: Confirmed text content, emitted verbatim.
        servers: Optional list of server names this workflow covers.
    """

    name: str
    compile_to: str  # target type: "mcp_instructions"
    priority: str  # "high" | "medium" | "low"
    text: str  # confirmed text, emitted verbatim
    servers: list[str] = field(default_factory=list)


def load_workflows(workflows_dir: Optional[Path] = None) -> list[WorkflowConfig]:
    """Load all workflow YAML files, validate, and return sorted by priority.

    Args:
        workflows_dir: Path to workflows/ directory. Defaults to
            /app/workflows (container) or ./workflows (development).

    Returns:
        List of WorkflowConfig sorted by priority (high > medium > low),
        then by filename within same priority.
    """
    if workflows_dir is None:
        candidates = [
            Path("/app/workflows"),
            Path("./workflows"),
            Path("../workflows"),
            Path("../../workflows"),
        ]
        for candidate in candidates:
            if candidate.is_dir():
                workflows_dir = candidate
                break

    if workflows_dir is None or not workflows_dir.is_dir():
        logger.debug("No workflows/ directory found, skipping workflow loading")
        return []

    workflows: list[tuple[int, str, WorkflowConfig]] = []

    for yaml_path in sorted(workflows_dir.glob("*.yaml")):
        try:
            with open(yaml_path) as f:
                raw = yaml.safe_load(f)
        except Exception:
            logger.exception(f"Failed to parse {yaml_path}")
            continue

        if not isinstance(raw, dict):
            logger.warning(f"Invalid workflow file (not a mapping): {yaml_path}")
            continue

        config = WorkflowConfig(
            name=raw.get("name", ""),
            compile_to=raw.get("compile_to", ""),
            priority=raw.get("priority", "medium"),
            text=raw.get("text", ""),
            servers=raw.get("servers", []),
        )

        errors = _validate(config)
        if errors:
            for error in errors:
                logger.error(f"Workflow '{yaml_path.name}': {error}")
            continue

        order = PRIORITY_ORDER.get(config.priority, 1)
        workflows.append((order, yaml_path.name, config))

    workflows.sort(key=lambda x: (x[0], x[1]))
    loaded = [wf for _, _, wf in workflows]

    logger.info(f"Loaded {len(loaded)} workflows from {workflows_dir}")
    return loaded


def _validate(config: WorkflowConfig) -> list[str]:
    """Validate a workflow configuration.

    Returns:
        List of validation error messages. Empty list means valid.
    """
    errors: list[str] = []

    if not config.name:
        errors.append("'name' is required")
    elif not _KEBAB_CASE_RE.match(config.name):
        errors.append(f"'name' must be kebab-case, got '{config.name}'")

    if config.priority not in _PRIORITY_VALUES:
        errors.append(f"'priority' must be high/medium/low, got '{config.priority}'")

    if not config.compile_to:
        errors.append("'compile_to' is required")

    if not config.text or not config.text.strip():
        errors.append("'text' is required and must not be empty")

    return errors
