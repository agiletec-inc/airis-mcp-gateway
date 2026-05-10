"""
Toolset catalog for Dynamic MCP capability activation.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolsetInfo:
    """Logical capability slice exposed to the model."""
    ref: str
    server: str
    name: str
    summary: str
    tools: list[str] = field(default_factory=list)


DEFAULT_TOOLSET_PATH = Path("/app/config/toolsets.json")
DEV_TOOLSET_PATH = Path("config/toolsets.json")


def _load_seed_catalog() -> dict:
    for path in (DEFAULT_TOOLSET_PATH, DEV_TOOLSET_PATH):
        if path.exists():
            with path.open() as f:
                return json.load(f)
    logger.info("No toolset catalog file found, using inferred defaults")
    return {}


def build_toolset_index(server_configs: dict[str, object]) -> dict[str, ToolsetInfo]:
    """
    Build toolset index from seed catalog plus tools_index fallback.
    """
    seed_catalog = _load_seed_catalog()
    toolsets: dict[str, ToolsetInfo] = {}

    for server_name, config in server_configs.items():
        indexed_tools = [
            entry.get("name")
            for entry in getattr(config, "tools_index", []) or []
            if entry.get("name")
        ]
        if not indexed_tools:
            continue

        assigned_tools: set[str] = set()
        server_seed = seed_catalog.get(server_name, {})
        for toolset_name, raw in server_seed.get("toolsets", {}).items():
            tools = [tool for tool in raw.get("tools", []) if tool in indexed_tools]
            if not tools:
                continue
            ref = f"{server_name}.{toolset_name}"
            toolsets[ref] = ToolsetInfo(
                ref=ref,
                server=server_name,
                name=toolset_name,
                summary=raw.get("summary", f"{server_name} {toolset_name} operations"),
                tools=tools,
            )
            assigned_tools.update(tools)

        remaining_tools = [tool for tool in indexed_tools if tool not in assigned_tools]
        if remaining_tools:
            ref = f"{server_name}.default"
            toolsets[ref] = ToolsetInfo(
                ref=ref,
                server=server_name,
                name="default",
                summary=f"Default capability slice for {server_name}",
                tools=remaining_tools,
            )

    return toolsets
