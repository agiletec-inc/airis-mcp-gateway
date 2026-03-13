"""Tests for routing_engine module."""

import json
import pytest
from unittest.mock import patch, mock_open

from app.core.routing_engine import (
    load_routing_table,
    format_routing_table_as_instructions,
    route_task,
    RouteResult,
    invalidate_cache,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear routing table cache before each test."""
    invalidate_cache()
    yield
    invalidate_cache()


SAMPLE_TABLE = {
    "routes": [
        {"pattern": "research|investigate|search web", "chain": ["tavily:search"], "hint": "Web research"},
        {"pattern": "database|sql|query", "chain": ["supabase:query"], "hint": "Database"},
        {"pattern": "payment|invoice|billing", "chain": ["stripe:*"], "hint": "Payments"},
    ]
}


class TestLoadRoutingTable:
    """Test load_routing_table function."""

    def test_file_not_found(self):
        """Returns empty dict when file doesn't exist."""
        result = load_routing_table("/nonexistent/path.json")
        assert result == {}

    def test_valid_json(self, tmp_path):
        """Loads and caches valid JSON."""
        f = tmp_path / "routing-table.json"
        f.write_text(json.dumps(SAMPLE_TABLE))
        result = load_routing_table(str(f))
        assert len(result["routes"]) == 3

    def test_invalid_json(self, tmp_path):
        """Returns empty dict for invalid JSON."""
        f = tmp_path / "bad.json"
        f.write_text("not json{")
        result = load_routing_table(str(f))
        assert result == {}

    def test_caching(self, tmp_path):
        """Returns cached result on second call."""
        f = tmp_path / "routing-table.json"
        f.write_text(json.dumps(SAMPLE_TABLE))
        path = str(f)
        result1 = load_routing_table(path)
        # Modify file - should still return cached
        f.write_text(json.dumps({"routes": []}))
        result2 = load_routing_table(path)
        assert result1 is result2


class TestFormatRoutingTableAsInstructions:
    """Test format_routing_table_as_instructions function."""

    def test_with_routes(self, tmp_path):
        """Formats routes as compact instruction text."""
        f = tmp_path / "routing-table.json"
        f.write_text(json.dumps(SAMPLE_TABLE))
        result = format_routing_table_as_instructions(str(f))
        assert "## Quick Routes" in result
        assert "Web research: tavily:search" in result
        assert "Database: supabase:query" in result

    def test_empty_table(self):
        """Returns empty string when no file exists."""
        result = format_routing_table_as_instructions("/nonexistent/path.json")
        assert result == ""


class TestRouteTask:
    """Test route_task function."""

    def test_matches_pattern(self):
        """Matches task against routing table patterns."""
        result = route_task("research best practices for React", routing_table=SAMPLE_TABLE)
        assert result.chain == ["tavily:search"]
        assert result.hint == "Web research"

    def test_database_pattern(self):
        """Matches database-related tasks."""
        result = route_task("query the users table", routing_table=SAMPLE_TABLE)
        assert result.chain == ["supabase:query"]
        assert result.hint == "Database"

    def test_no_match(self):
        """Returns empty chain when no pattern matches."""
        result = route_task("deploy to production", routing_table=SAMPLE_TABLE)
        assert result.chain == []
        assert result.hint == ""

    def test_empty_routing_table(self):
        """Handles empty routing table gracefully."""
        result = route_task("research something", routing_table={})
        assert result.chain == []

    def test_suggestions_included(self):
        """Includes tool suggestions even without route match."""
        result = route_task("create a stripe invoice", routing_table=SAMPLE_TABLE)
        # Should match "invoice" pattern and also get suggestions
        assert result.chain == ["stripe:*"]
        assert isinstance(result.suggestions, list)

    def test_result_to_dict(self):
        """RouteResult serializes correctly."""
        result = RouteResult(
            chain=["tavily:search"],
            hint="Web research",
            suggestions=[{"server": "tavily", "tool": "search", "score": 0.8, "reason": "test"}],
            pattern="research",
        )
        d = result.to_dict()
        assert d["chain"] == ["tavily:search"]
        assert d["hint"] == "Web research"
        assert len(d["suggestions"]) == 1
