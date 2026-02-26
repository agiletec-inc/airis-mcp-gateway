"""MCP Tool Suggestion Service.

Suggests appropriate MCP tools from airis-mcp-gateway based on natural language intent.
Integrates with Dynamic MCP to provide intelligent tool discovery.

Example:
    request = SuggestToolRequest(intent="Create an invoice with Stripe")
    response = suggest_tool(request)
    # Returns suggestions like: [ToolSuggestion(server="stripe", tool="create_invoice", ...)]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .dynamic_mcp import DynamicMCP


@dataclass
class SuggestToolRequest:
    """Request for tool suggestion.

    Attributes:
        intent: Natural language intent (e.g., "Create invoice with Stripe")
        context: Optional context dictionary
        max_results: Maximum suggestions to return
    """

    intent: str  # Natural language intent
    context: Dict[str, Any] = field(default_factory=dict)  # Optional context
    max_results: int = 5  # Maximum suggestions to return


@dataclass
class ToolSuggestion:
    """A single tool suggestion.

    Attributes:
        server: MCP server name (e.g., "stripe")
        tool: Tool name (e.g., "create_invoice")
        score: Match score (0.0 - 1.0)
        reason: Explanation for the suggestion
    """

    server: str  # MCP server name
    tool: str  # Tool name
    score: float  # Match score (0.0 - 1.0)
    reason: str  # Explanation for the suggestion

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "server": self.server,
            "tool": self.tool,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass
class SuggestToolResponse:
    """Response containing tool suggestions.

    Attributes:
        suggestions: List of tool suggestions ranked by score
        query_keywords: Extracted keywords from intent
    """

    suggestions: List[ToolSuggestion]
    query_keywords: List[str]  # Extracted keywords from intent

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "suggestions": [s.to_dict() for s in self.suggestions],
            "query_keywords": self.query_keywords,
        }


# Known MCP tool categories with common keywords
# This serves as a fallback when we can't fetch from DynamicMCP
TOOL_CATALOG: Dict[str, Dict[str, List[str]]] = {
    "memory": {
        "create_entities": ["memory", "entity", "create", "store", "save", "knowledge"],
        "search_nodes": ["memory", "search", "find", "query", "retrieve", "knowledge"],
        "add_observations": ["memory", "observation", "add", "note", "record"],
        "delete_entities": ["memory", "entity", "delete", "remove"],
    },
    "filesystem": {
        "read_file": ["file", "read", "open", "content", "view"],
        "write_file": ["file", "write", "save", "create", "output"],
        "list_directory": ["directory", "list", "folder", "files", "ls"],
        "search_files": ["file", "search", "find", "glob", "pattern"],
    },
    "git": {
        "status": ["git", "status", "changes", "modified"],
        "diff": ["git", "diff", "changes", "compare"],
        "commit": ["git", "commit", "save", "snapshot"],
        "log": ["git", "log", "history", "commits"],
    },
    "browser": {
        "navigate": ["browser", "navigate", "url", "open", "visit", "web"],
        "screenshot": ["browser", "screenshot", "capture", "image"],
        "click": ["browser", "click", "button", "element"],
        "type": ["browser", "type", "input", "text", "form"],
    },
    "stripe": {
        "create_invoice": ["stripe", "invoice", "create", "billing", "payment"],
        "list_customers": ["stripe", "customer", "list", "billing"],
        "create_payment_intent": ["stripe", "payment", "intent", "charge"],
    },
    "tavily": {
        "search": ["search", "web", "internet", "tavily", "research"],
    },
    "context7": {
        "resolve-library-id": ["docs", "documentation", "library", "official", "api"],
        "get-library-docs": ["docs", "documentation", "library", "reference"],
    },
    "serena": {
        "get_project_summary": ["project", "summary", "overview", "codebase"],
        "find_symbol": ["symbol", "find", "search", "code", "function", "class"],
        "get_file_summary": ["file", "summary", "overview"],
    },
    "sequential-thinking": {
        "think": ["think", "reason", "analyze", "step", "sequential"],
    },
    "github": {
        "create_issue": ["github", "issue", "create", "bug", "feature"],
        "list_issues": ["github", "issue", "list", "bugs", "features"],
        "create_pull_request": ["github", "pr", "pull", "request", "merge"],
    },
    "supabase": {
        "query": ["supabase", "database", "query", "sql", "postgres"],
        "insert": ["supabase", "insert", "add", "create", "database"],
    },
    "playwright": {
        "navigate": ["browser", "playwright", "navigate", "page", "url"],
        "click": ["browser", "playwright", "click", "element", "button"],
        "screenshot": ["browser", "playwright", "screenshot", "capture"],
    },
}

# Keyword synonyms for better matching
KEYWORD_SYNONYMS: Dict[str, List[str]] = {
    "create": ["make", "new", "add", "generate", "build"],
    "read": ["get", "fetch", "retrieve", "view", "show", "display"],
    "write": ["save", "store", "update", "put", "set"],
    "delete": ["remove", "destroy", "clear", "drop"],
    "search": ["find", "query", "lookup", "locate", "look"],
    "list": ["show", "display", "enumerate", "get"],
    "file": ["document", "doc", "content"],
    "memory": ["knowledge", "store", "remember", "recall"],
    "invoice": ["bill", "billing", "charge"],
    "payment": ["pay", "charge", "transaction", "money"],
    "customer": ["client", "user", "account"],
    "browser": ["web", "page", "site", "url"],
    "code": ["source", "program", "script"],
}


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from text.

    Args:
        text: Input text (natural language intent)

    Returns:
        List of extracted and expanded keywords
    """
    # Lowercase and split by non-alphanumeric characters
    words = re.split(r"[^a-zA-Z0-9]+", text.lower())

    # Filter out common stopwords and short words
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "must", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after",
        "above", "below", "between", "under", "again", "further",
        "then", "once", "here", "there", "when", "where", "why",
        "how", "all", "each", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "just", "also", "now", "i",
        "me", "my", "we", "our", "you", "your", "it", "its",
        "want", "need", "like", "please", "help", "using", "use",
    }

    keywords = [w for w in words if w and len(w) > 2 and w not in stopwords]

    # Expand synonyms
    expanded = set(keywords)
    for keyword in keywords:
        for canonical, synonyms in KEYWORD_SYNONYMS.items():
            if keyword in synonyms:
                expanded.add(canonical)
            if keyword == canonical:
                expanded.update(synonyms)

    return list(expanded)


def _calculate_match_score(
    keywords: List[str], tool_keywords: List[str]
) -> Tuple[float, List[str]]:
    """Calculate match score between intent keywords and tool keywords.

    Args:
        keywords: Keywords from user intent
        tool_keywords: Keywords associated with the tool

    Returns:
        Tuple of (score, matched_keywords)
    """
    if not keywords or not tool_keywords:
        return 0.0, []

    matches = []
    keyword_set = set(keywords)
    tool_keyword_set = set(tool_keywords)

    # Direct matches
    direct_matches = keyword_set & tool_keyword_set
    matches.extend(direct_matches)

    # Score calculation
    # Weight direct matches heavily
    if not matches:
        return 0.0, []

    # Score = matched / max(intent_keywords, tool_keywords)
    # This rewards tools that match well without requiring all keywords
    score = len(matches) / max(len(keyword_set), len(tool_keyword_set))

    # Bonus for matching multiple keywords
    if len(matches) >= 2:
        score = min(1.0, score * 1.2)

    return round(score, 2), list(matches)


def suggest_tool(
    request: SuggestToolRequest,
    dynamic_mcp: Optional["DynamicMCP"] = None,
) -> SuggestToolResponse:
    """
    Suggest MCP tools based on natural language intent.

    The function:
    1. Extracts keywords from the intent
    2. Matches against known tool catalog and/or DynamicMCP cache
    3. Returns ranked suggestions with scores

    Args:
        request: SuggestToolRequest with intent and optional context
        dynamic_mcp: Optional DynamicMCP instance for live tool lookup

    Returns:
        SuggestToolResponse with ranked tool suggestions
    """
    keywords = _extract_keywords(request.intent)

    if not keywords:
        return SuggestToolResponse(suggestions=[], query_keywords=[])

    suggestions: List[ToolSuggestion] = []

    # First, try to match against DynamicMCP cached tools
    if dynamic_mcp and dynamic_mcp._tools:
        for tool_name, tool_info in dynamic_mcp._tools.items():
            # Build keywords from tool name and description
            tool_keywords = _extract_keywords(
                f"{tool_info.server} {tool_name} {tool_info.description}"
            )

            score, matched = _calculate_match_score(keywords, tool_keywords)

            if score > 0:
                reason = f"Matched: {', '.join(matched)}" if matched else "Partial match"
                suggestions.append(
                    ToolSuggestion(
                        server=tool_info.server,
                        tool=tool_name,
                        score=score,
                        reason=reason,
                    )
                )

    # Also match against static tool catalog (for tools not yet loaded)
    for server, tools in TOOL_CATALOG.items():
        for tool_name, tool_keywords in tools.items():
            # Skip if already matched from DynamicMCP
            if any(s.server == server and s.tool == tool_name for s in suggestions):
                continue

            score, matched = _calculate_match_score(keywords, tool_keywords)

            if score > 0:
                reason = f"Matched: {', '.join(matched)}" if matched else "Partial match"
                suggestions.append(
                    ToolSuggestion(
                        server=server,
                        tool=tool_name,
                        score=score,
                        reason=reason,
                    )
                )

    # Sort by score descending
    suggestions.sort(key=lambda x: x.score, reverse=True)

    # Limit results
    suggestions = suggestions[: request.max_results]

    return SuggestToolResponse(
        suggestions=suggestions,
        query_keywords=keywords,
    )


def format_suggestions_as_text(response: SuggestToolResponse) -> str:
    """Format suggestions as human-readable text.

    Args:
        response: SuggestToolResponse to format

    Returns:
        Formatted text string
    """
    lines = []

    if not response.suggestions:
        lines.append("No tool suggestions found for the given intent.")
        lines.append(f"Keywords extracted: {', '.join(response.query_keywords)}")
        lines.append("\nTry using airis-find with different search terms.")
        return "\n".join(lines)

    lines.append(f"## Tool Suggestions")
    lines.append(f"Keywords: {', '.join(response.query_keywords)}")
    lines.append("")

    for i, suggestion in enumerate(response.suggestions, 1):
        score_pct = int(suggestion.score * 100)
        lines.append(
            f"{i}. **{suggestion.server}:{suggestion.tool}** (score: {score_pct}%)"
        )
        lines.append(f"   {suggestion.reason}")

    lines.append("")
    lines.append("Use `airis-schema` to get the input schema for any of these tools.")
    lines.append("Use `airis-exec` to execute a tool.")

    return "\n".join(lines)


# Convenience exports
__all__ = [
    "SuggestToolRequest",
    "SuggestToolResponse",
    "ToolSuggestion",
    "suggest_tool",
    "format_suggestions_as_text",
]
