"""Routing engine for proactive tool orchestration.

Matches task descriptions against routing-table.json patterns
and enriches results with airis-suggest scores.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .logging import get_logger
from .tool_suggester import SuggestToolRequest, suggest_tool

if TYPE_CHECKING:
    from .dynamic_mcp import DynamicMCP

logger = get_logger(__name__)

# Default path inside Docker container
DEFAULT_ROUTING_TABLE_PATH = "/app/routing-table.json"

# Module-level cache
_routing_table: Optional[Dict[str, Any]] = None
_routing_table_path: Optional[str] = None


@dataclass
class RouteResult:
    """Result of routing a task to tool chains.

    Attributes:
        chain: Matched tool chain from routing table
        hint: Human-readable hint for the route
        suggestions: Additional tool suggestions from airis-suggest
        pattern: The regex pattern that matched
    """

    chain: List[str]
    hint: str
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    pattern: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "chain": self.chain,
            "hint": self.hint,
            "suggestions": self.suggestions,
            "pattern": self.pattern,
        }


def load_routing_table(path: str = DEFAULT_ROUTING_TABLE_PATH) -> Dict[str, Any]:
    """Load routing table from JSON file with caching.

    Args:
        path: Path to routing-table.json

    Returns:
        Parsed routing table dict, or empty dict if not found
    """
    global _routing_table, _routing_table_path

    # Return cached if same path
    if _routing_table is not None and _routing_table_path == path:
        return _routing_table

    try:
        with open(path) as f:
            _routing_table = json.load(f)
            _routing_table_path = path
            logger.info(f"Loaded routing table from {path} ({len(_routing_table.get('routes', []))} routes)")
            return _routing_table
    except FileNotFoundError:
        logger.debug(f"Routing table not found at {path}, returning empty")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in routing table {path}: {e}")
        return {}


def format_routing_table_as_instructions(path: str = DEFAULT_ROUTING_TABLE_PATH) -> str:
    """Format routing table as compact instructions text for MCP initialize response.

    Args:
        path: Path to routing-table.json

    Returns:
        Formatted instructions string, or empty string if not available
    """
    table = load_routing_table(path)
    if not table or "routes" not in table:
        return ""

    routes = table["routes"]
    parts = []
    for route in routes:
        hint = route.get("hint", "")
        chain = route.get("chain", [])
        chain_str = " → ".join(chain)
        parts.append(f"{hint}: {chain_str}")

    return "## Quick Routes\n" + " | ".join(parts)


def route_task(
    task: str,
    routing_table: Optional[Dict[str, Any]] = None,
    dynamic_mcp: Optional["DynamicMCP"] = None,
    max_results: int = 5,
) -> RouteResult:
    """Route a task description to optimal tool chains.

    Matches task against routing-table patterns (regex), then
    enriches with airis-suggest scores from tool_suggester.

    Args:
        task: Natural language task description
        routing_table: Pre-loaded routing table (loads from default path if None)
        dynamic_mcp: DynamicMCP instance for suggestion enrichment
        max_results: Maximum suggestions to include

    Returns:
        RouteResult with matched chain, hint, and suggestions
    """
    if routing_table is None:
        routing_table = load_routing_table()

    # Match against routing table patterns
    matched_chain: List[str] = []
    matched_hint = ""
    matched_pattern = ""

    task_lower = task.lower()
    routes = routing_table.get("routes", [])

    for route in routes:
        pattern = route.get("pattern", "")
        if not pattern:
            continue
        try:
            if re.search(pattern, task_lower):
                matched_chain = route.get("chain", [])
                matched_hint = route.get("hint", "")
                matched_pattern = pattern
                break
        except re.error as e:
            logger.warning(f"Invalid regex in routing table: {pattern}: {e}")
            continue

    # Enrich with airis-suggest
    suggestions: List[Dict[str, Any]] = []
    try:
        request = SuggestToolRequest(intent=task, max_results=max_results)
        response = suggest_tool(request, dynamic_mcp=dynamic_mcp)
        suggestions = [s.to_dict() for s in response.suggestions]
    except Exception as e:
        logger.warning(f"Failed to get suggestions for route: {e}")

    return RouteResult(
        chain=matched_chain,
        hint=matched_hint,
        suggestions=suggestions,
        pattern=matched_pattern,
    )


def invalidate_cache() -> None:
    """Invalidate the routing table cache (useful for testing or hot-reload)."""
    global _routing_table, _routing_table_path
    _routing_table = None
    _routing_table_path = None
