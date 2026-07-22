"""
OpenMCP Lazy Loading Pattern Implementation

Schema partitioning logic for 75-90% token consumption reduction.
"""

from typing import Any, Dict, List, Optional
import copy


class SchemaPartitioner:
    """
    Partitions JSON Schema to top-level properties only.

    OpenMCP Pattern:
    - tools/list: Returns lightweight schema (top-level only)
    - expandSchema: Retrieves details progressively as needed
    """

    def __init__(self):
        # Cache full schemas in memory
        self.full_schemas: Dict[str, Dict[str, Any]] = {}
        self.tool_docs: Dict[str, str] = {}

    def store_full_schema(self, tool_name: str, full_schema: Dict[str, Any]):
        """
        Store full schema for expandSchema use.

        Args:
            tool_name: Tool name
            full_schema: Complete inputSchema
        """
        self.full_schemas[tool_name] = copy.deepcopy(full_schema)
        # Docs are managed separately since tool itself may be mutated

    def store_tool_description(self, tool_name: str, description: Optional[str]):
        """Store tool description for lazy loading."""
        if description:
            self.tool_docs[tool_name] = description.strip()

    def get_tool_description(self, tool_name: str) -> Optional[str]:
        """Retrieve stored tool description."""
        return self.tool_docs.get(tool_name)

    def partition_schema(
        self, schema: Dict[str, Any], depth: int = 1
    ) -> Dict[str, Any]:
        """
        Partition schema to top-level properties only.

        Args:
            schema: Original JSON Schema
            depth: Depth of hierarchy to retain (default: 1 = top-level only)

        Returns:
            Lightweight schema

        Example:
            Input (1000 tokens):
            {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "shipping": {
                                "type": "object",
                                "properties": {
                                    "address": {...}
                                }
                            }
                        }
                    }
                }
            }

            Output (50 tokens):
            {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "metadata": {"type": "object"}  # Nested removed
                }
            }
        """
        if not isinstance(schema, dict):
            return schema

        partitioned = copy.deepcopy(schema)

        # If properties exist
        if "properties" in partitioned and depth > 0:
            new_properties = {}

            for key, value in partitioned["properties"].items():
                if isinstance(value, dict):
                    # Keep only top-level type and description
                    new_prop = {}

                    if "type" in value:
                        new_prop["type"] = value["type"]

                    if "description" in value:
                        new_prop["description"] = value["description"]

                    # Keep enum and const (needed for choices)
                    if "enum" in value:
                        new_prop["enum"] = value["enum"]

                    if "const" in value:
                        new_prop["const"] = value["const"]

                    # Keep format, pattern and other validations
                    if "format" in value:
                        new_prop["format"] = value["format"]

                    if "pattern" in value:
                        new_prop["pattern"] = value["pattern"]

                    # Keep required and default
                    if "required" in value:
                        new_prop["required"] = value["required"]

                    if "default" in value:
                        new_prop["default"] = value["default"]

                    # For arrays, recursively partition items
                    if value.get("type") == "array" and isinstance(
                        value.get("items"), dict
                    ):
                        new_prop["items"] = self.partition_schema(
                            value["items"], max(depth - 1, 0)
                        )

                    # Nested properties are removed (only type info remains)
                    # This achieves token reduction

                    new_properties[key] = new_prop
                else:
                    new_properties[key] = value

            partitioned["properties"] = new_properties

        # If items exist (array)
        if "items" in partitioned and isinstance(partitioned["items"], dict):
            partitioned["items"] = self.partition_schema(
                partitioned["items"], depth - 1
            )

        return partitioned

    def expand_schema(
        self, tool_name: str, path: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get schema details for the specified path.

        Args:
            tool_name: Tool name
            path: Schema path (e.g., ["metadata", "shipping"])
                  If None, returns the complete schema

        Returns:
            Schema at specified path, or None if not found

        Example:
            expand_schema("stripe_create_payment", ["metadata", "shipping"])
            -> Returns complete schema under metadata.shipping
        """
        if tool_name not in self.full_schemas:
            return None

        schema = self.full_schemas[tool_name]

        # No path specified = complete schema
        if not path:
            return copy.deepcopy(schema)

        # Traverse the path
        current = schema
        for key in path:
            if isinstance(current, dict):
                if key in current:
                    current = current[key]
                elif "properties" in current and key in current["properties"]:
                    current = current["properties"][key]
                else:
                    return None
            else:
                return None

        return copy.deepcopy(current)

    def get_token_reduction_estimate(
        self, full_schema: Dict[str, Any]
    ) -> Dict[str, int]:
        """
        Estimate token reduction effect.

        Args:
            full_schema: Complete schema

        Returns:
            {"full": estimated full tokens, "partitioned": estimated partitioned tokens, "reduction": reduction %}
        """
        import json

        full_json = json.dumps(full_schema)
        partitioned_json = json.dumps(self.partition_schema(full_schema))

        # Use JSON length as token approximation (roughly 4 chars = 1 token)
        full_tokens = len(full_json) // 4
        partitioned_tokens = len(partitioned_json) // 4

        reduction = (
            int((1 - partitioned_tokens / full_tokens) * 100) if full_tokens > 0 else 0
        )

        return {
            "full": full_tokens,
            "partitioned": partitioned_tokens,
            "reduction": reduction,
        }


# Global instance (shared by FastAPI)
schema_partitioner = SchemaPartitioner()
