"""Unit tests for schema_partitioning.py"""

import pytest
from app.core.schema_partitioning import SchemaPartitioner


@pytest.fixture
def partitioner():
    """Create SchemaPartitioner instance"""
    return SchemaPartitioner()


def test_partition_simple_schema(partitioner):
    """Test partitioning a simple schema with no nesting"""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "User name"},
            "age": {"type": "number", "description": "User age"},
        },
    }

    result = partitioner.partition_schema(schema)

    # Simple schema should remain unchanged
    assert result["type"] == "object"
    assert "name" in result["properties"]
    assert "age" in result["properties"]
    assert result["properties"]["name"]["type"] == "string"
    assert result["properties"]["name"]["description"] == "User name"


def test_partition_nested_schema(partitioner):
    """Test partitioning a deeply nested schema"""
    schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Payment amount"},
            "metadata": {
                "type": "object",
                "description": "Payment metadata",
                "properties": {
                    "shipping": {
                        "type": "object",
                        "properties": {
                            "address": {
                                "type": "object",
                                "properties": {
                                    "line1": {"type": "string"},
                                    "line2": {"type": "string"},
                                    "city": {"type": "string"},
                                    "state": {"type": "string"},
                                    "postal_code": {"type": "string"},
                                    "country": {"type": "string"},
                                },
                            }
                        },
                    }
                },
            },
        },
    }

    result = partitioner.partition_schema(schema)

    # Top-level properties should exist
    assert "amount" in result["properties"]
    assert "metadata" in result["properties"]

    # amount should be unchanged (simple type)
    assert result["properties"]["amount"]["type"] == "number"

    # metadata should keep type and description
    assert result["properties"]["metadata"]["type"] == "object"
    assert result["properties"]["metadata"]["description"] == "Payment metadata"

    # metadata nested properties should be removed
    assert "properties" not in result["properties"]["metadata"]


def test_partition_preserves_enum(partitioner):
    """Test that enum values are preserved"""
    schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "approved", "rejected"],
                "description": "Payment status",
            }
        },
    }

    result = partitioner.partition_schema(schema)

    assert "status" in result["properties"]
    assert result["properties"]["status"]["enum"] == ["pending", "approved", "rejected"]


def test_partition_preserves_format(partitioner):
    """Test that format validators are preserved"""
    schema = {
        "type": "object",
        "properties": {
            "email": {"type": "string", "format": "email", "description": "User email"},
            "url": {"type": "string", "format": "uri", "description": "Website URL"},
        },
    }

    result = partitioner.partition_schema(schema)

    assert result["properties"]["email"]["format"] == "email"
    assert result["properties"]["url"]["format"] == "uri"


def test_partition_preserves_pattern(partitioner):
    """Test that regex patterns are preserved"""
    schema = {
        "type": "object",
        "properties": {
            "phone": {
                "type": "string",
                "pattern": r"^\d{3}-\d{4}$",
                "description": "Phone number",
            }
        },
    }

    result = partitioner.partition_schema(schema)

    assert result["properties"]["phone"]["pattern"] == r"^\d{3}-\d{4}$"


def test_partition_preserves_required(partitioner):
    """Test that required field info is preserved"""
    schema = {
        "type": "object",
        "properties": {"field": {"type": "string", "required": True}},
    }

    result = partitioner.partition_schema(schema)

    assert result["properties"]["field"]["required"] is True


def test_partition_preserves_default(partitioner):
    """Test that default values are preserved"""
    schema = {
        "type": "object",
        "properties": {"count": {"type": "number", "default": 10}},
    }

    result = partitioner.partition_schema(schema)

    assert result["properties"]["count"]["default"] == 10


def test_store_full_schema(partitioner):
    """Test storing full schema"""
    schema = {"type": "object", "properties": {"field": {"type": "string"}}}

    partitioner.store_full_schema("test_tool", schema)

    assert "test_tool" in partitioner.full_schemas
    assert partitioner.full_schemas["test_tool"] == schema


def test_expand_schema_full(partitioner):
    """Test expanding full schema (no path)"""
    schema = {"type": "object", "properties": {"field": {"type": "string"}}}

    partitioner.store_full_schema("test_tool", schema)
    expanded = partitioner.expand_schema("test_tool")

    assert expanded is not None
    assert expanded == schema
    # Verify deep copy (not same object)
    assert expanded is not schema


def test_expand_schema_path(partitioner):
    """Test expanding specific path in schema"""
    schema = {
        "type": "object",
        "properties": {
            "metadata": {
                "type": "object",
                "properties": {
                    "shipping": {
                        "type": "object",
                        "properties": {
                            "address": {
                                "type": "object",
                                "properties": {
                                    "line1": {"type": "string"},
                                    "city": {"type": "string"},
                                },
                            }
                        },
                    }
                },
            }
        },
    }

    partitioner.store_full_schema("test_tool", schema)

    # Expand metadata.shipping.address
    expanded = partitioner.expand_schema(
        "test_tool", ["metadata", "shipping", "address"]
    )

    assert expanded is not None
    assert expanded["type"] == "object"
    assert "line1" in expanded["properties"]
    assert "city" in expanded["properties"]


def test_expand_schema_invalid_path(partitioner):
    """Test expanding with invalid path"""
    schema = {"type": "object", "properties": {"field": {"type": "string"}}}

    partitioner.store_full_schema("test_tool", schema)

    # Non-existent path
    expanded = partitioner.expand_schema("test_tool", ["non_existent", "path"])

    assert expanded is None


def test_expand_schema_unknown_tool(partitioner):
    """Test expanding schema for unknown tool"""
    expanded = partitioner.expand_schema("unknown_tool")

    assert expanded is None


def test_get_token_reduction_estimate(partitioner):
    """Test token reduction estimation"""
    # Large nested schema
    schema = {
        "type": "object",
        "properties": {
            "simple": {"type": "string"},
            "nested": {
                "type": "object",
                "properties": {
                    "deep": {
                        "type": "object",
                        "properties": {
                            "field1": {"type": "string", "description": "A" * 100},
                            "field2": {"type": "string", "description": "B" * 100},
                            "field3": {"type": "string", "description": "C" * 100},
                            "field4": {"type": "string", "description": "D" * 100},
                        },
                    }
                },
            },
        },
    }

    estimate = partitioner.get_token_reduction_estimate(schema)

    # Verify structure
    assert "full" in estimate
    assert "partitioned" in estimate
    assert "reduction" in estimate

    # Verify reduction is significant
    assert estimate["full"] > estimate["partitioned"]
    assert estimate["reduction"] > 50  # At least 50% reduction


def test_partition_array_schema(partitioner):
    """Test partitioning schema with array items"""
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nested": {
                            "type": "object",
                            "properties": {"deep": {"type": "string"}},
                        }
                    },
                },
            }
        },
    }

    result = partitioner.partition_schema(schema)

    # Array items should be partitioned recursively
    assert result["properties"]["items"]["type"] == "array"
    assert "items" in result["properties"]["items"]


def test_partition_preserves_const(partitioner):
    """Test that const values are preserved"""
    schema = {
        "type": "object",
        "properties": {
            "version": {
                "type": "string",
                "const": "1.3.0",
                "description": "API version",
            }
        },
    }

    result = partitioner.partition_schema(schema)

    assert result["properties"]["version"]["const"] == "1.3.0"


def test_partition_empty_schema(partitioner):
    """Test partitioning empty schema"""
    schema = {"type": "object", "properties": {}}

    result = partitioner.partition_schema(schema)

    assert result["type"] == "object"
    assert result["properties"] == {}


def test_partition_non_dict_input(partitioner):
    """Test partitioning non-dict input"""
    result = partitioner.partition_schema("not a dict")

    # Should return as-is
    assert result == "not a dict"


def test_expand_schema_properties_path(partitioner):
    """Test expanding path that includes 'properties' keyword"""
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "number"}},
            }
        },
    }

    partitioner.store_full_schema("test_tool", schema)

    # Path should work with or without 'properties'
    expanded1 = partitioner.expand_schema("test_tool", ["user"])
    expanded2 = partitioner.expand_schema("test_tool", ["properties", "user"])

    # Both should return user schema
    assert expanded1 is not None
    assert expanded2 is not None
    assert expanded1["type"] == "object"
