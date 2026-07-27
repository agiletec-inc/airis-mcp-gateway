"""Tests for schema partitioning functionality."""

import json
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app.core.schema_partitioning import (
    partition_schema,
    partition_tool,
    partition_tools_list,
    inject_expand_schema_tool,
    get_schema_at_path,
    EXPAND_SCHEMA_TOOL,
)


class TestPartitionSchema:
    """Tests for partition_schema function."""

    def test_simple_schema(self):
        """Simple schema should remain unchanged."""
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
        }
        result = partition_schema(schema)
        assert result["type"] == "object"
        assert "query" in result["properties"]
        assert result["properties"]["query"]["type"] == "string"

    def test_nested_schema_is_partitioned(self):
        """Nested schemas should be simplified."""
        schema = {
            "type": "object",
            "properties": {
                "options": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "filters": {
                            "type": "object",
                            "properties": {"status": {"type": "string"}},
                        },
                    },
                }
            },
        }
        result = partition_schema(schema)

        # Top level should exist
        assert "options" in result["properties"]
        # But nested details should be stripped
        options = result["properties"]["options"]
        assert options["type"] == "object"
        assert options.get("_partitioned") is True
        # Nested properties should not be present
        assert "properties" not in options or "limit" not in options.get(
            "properties", {}
        )

    def test_array_schema(self):
        """Array schemas should have items simplified."""
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "nested": {
                                "type": "object",
                                "properties": {"deep": {"type": "string"}},
                            },
                        },
                    },
                }
            },
        }
        result = partition_schema(schema)
        items_prop = result["properties"]["items"]
        assert items_prop["type"] == "array"
        assert items_prop.get("_partitioned") is True

    def test_preserves_essential_fields(self):
        """Essential fields like enum, format should be preserved."""
        schema = {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "inactive"],
                    "description": "Status value",
                },
                "email": {"type": "string", "format": "email"},
            },
        }
        result = partition_schema(schema)
        assert result["properties"]["status"]["enum"] == ["active", "inactive"]
        assert result["properties"]["email"]["format"] == "email"


class TestPartitionTool:
    """Tests for partition_tool function."""

    def test_partitions_input_schema(self):
        """Tool's inputSchema should be partitioned."""
        tool = {
            "name": "test_tool",
            "description": "A test tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {"nested": {"type": "string"}},
                    }
                },
            },
        }
        result = partition_tool(tool)
        assert result["name"] == "test_tool"
        assert result["description"] == "A test tool"
        config = result["inputSchema"]["properties"]["config"]
        assert config["type"] == "object"
        assert config.get("_partitioned") is True


class TestPartitionToolsList:
    """Tests for partition_tools_list function."""

    def test_partitions_all_tools(self):
        """All tools in list should be partitioned."""
        tools = [
            {"name": "tool1", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "tool2", "inputSchema": {"type": "object", "properties": {}}},
        ]
        result = partition_tools_list(tools)
        assert len(result) == 2
        assert result[0]["name"] == "tool1"
        assert result[1]["name"] == "tool2"


class TestInjectExpandSchemaTool:
    """Tests for inject_expand_schema_tool function."""

    def test_injects_tool(self):
        """expandSchema tool should be injected."""
        tools = [{"name": "existing_tool"}]
        result = inject_expand_schema_tool(tools)
        assert len(result) == 2
        assert result[0]["name"] == "expandSchema"
        assert result[1]["name"] == "existing_tool"

    def test_no_duplicate_injection(self):
        """Should not inject if already present."""
        tools = [EXPAND_SCHEMA_TOOL, {"name": "other_tool"}]
        result = inject_expand_schema_tool(tools)
        assert len(result) == 2


class TestGetSchemaAtPath:
    """Tests for get_schema_at_path function."""

    def test_gets_nested_property(self):
        """Should retrieve nested property schema."""
        schema = {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "database": {
                            "type": "object",
                            "properties": {"host": {"type": "string"}},
                        }
                    },
                }
            },
        }
        result = get_schema_at_path(schema, ["config", "database"])
        assert result["type"] == "object"
        assert "host" in result["properties"]

    def test_returns_none_for_invalid_path(self):
        """Should return None for non-existent path."""
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = get_schema_at_path(schema, ["nonexistent"])
        assert result is None


class TestTokenSavings:
    """Tests to verify token savings."""

    def test_significant_reduction(self):
        """Partitioning should significantly reduce schema size."""
        # Complex schema with deep nesting
        complex_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "options": {
                    "type": "object",
                    "description": "Search options",
                    "properties": {
                        "pagination": {
                            "type": "object",
                            "properties": {
                                "page": {"type": "integer", "default": 1},
                                "limit": {"type": "integer", "default": 10},
                                "cursor": {"type": "string"},
                            },
                        },
                        "filters": {
                            "type": "object",
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "enum": ["active", "archived"],
                                },
                                "tags": {"type": "array", "items": {"type": "string"}},
                                "dateRange": {
                                    "type": "object",
                                    "properties": {
                                        "start": {"type": "string", "format": "date"},
                                        "end": {"type": "string", "format": "date"},
                                    },
                                },
                            },
                        },
                        "sort": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "order": {"type": "string", "enum": ["asc", "desc"]},
                            },
                        },
                    },
                },
            },
        }

        full_size = len(json.dumps(complex_schema))
        partitioned = partition_schema(complex_schema)
        partitioned_size = len(json.dumps(partitioned))

        reduction = (full_size - partitioned_size) / full_size * 100
        print(
            f"\nFull: {full_size} chars, Partitioned: {partitioned_size} chars, Reduction: {reduction:.1f}%"
        )

        # Should achieve at least 30% reduction for complex schemas
        assert reduction > 30, f"Expected >30% reduction, got {reduction:.1f}%"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
