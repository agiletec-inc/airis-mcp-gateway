"""
Unit tests for Behavior Compiler.

Tests cover:
- Base instructions output when no behaviors defined
- HOT server tool reference format (direct)
- COLD server tool reference format (airis-exec)
- Priority sorting (high > medium > low)
- Disabled servers with behavior (included for auto-enable)
- Routing table integration (Quick Routes section)
"""

import pytest
from unittest.mock import patch

from app.core.behavior_compiler import (
    compile_instructions,
    _compile_behavior_lines,
    _BASE_INSTRUCTIONS,
    _META_TOOLS_SECTION,
)
from app.core.mcp_config_loader import (
    McpServerConfig,
    BehaviorConfig,
    ServerType,
    ServerMode,
)


def _make_server(
    name: str,
    mode: ServerMode = ServerMode.COLD,
    enabled: bool = True,
    behavior: BehaviorConfig | None = None,
) -> McpServerConfig:
    """Helper to create McpServerConfig for tests."""
    return McpServerConfig(
        name=name,
        server_type=ServerType.PROCESS,
        command="npx",
        args=[],
        env={},
        enabled=enabled,
        mode=mode,
        behavior=behavior,
    )


class TestCompileInstructions:
    """Test the main compile_instructions function."""

    @patch("app.core.behavior_compiler.format_routing_table_as_instructions", return_value="")
    def test_no_behaviors_returns_base_only(self, mock_routing):
        """When no servers have behavior, output contains base + meta-tools only."""
        configs = {
            "server-a": _make_server("server-a"),
        }
        result = compile_instructions(configs)

        assert _BASE_INSTRUCTIONS in result
        assert _META_TOOLS_SECTION in result
        assert "## Proactive Tool Usage" not in result

    @patch("app.core.behavior_compiler.format_routing_table_as_instructions", return_value="")
    def test_with_behaviors_includes_proactive_section(self, mock_routing):
        """When servers have behavior, Proactive Tool Usage section is included."""
        configs = {
            "context7": _make_server(
                "context7",
                mode=ServerMode.HOT,
                behavior=BehaviorConfig(
                    triggers=["implementing with library"],
                    instruction="Lookup docs BEFORE writing code",
                    priority="high",
                ),
            ),
        }
        result = compile_instructions(configs)

        assert "## Proactive Tool Usage" in result
        assert "WHEN implementing with library" in result
        assert "Lookup docs BEFORE writing code" in result

    @patch("app.core.behavior_compiler.format_routing_table_as_instructions", return_value="## Quick Routes\nWeb: tavily:search")
    def test_routing_table_appended(self, mock_routing):
        """Quick Routes section from routing table is appended."""
        configs = {}
        result = compile_instructions(configs)

        assert "## Quick Routes" in result
        assert "Web: tavily:search" in result

    @patch("app.core.behavior_compiler.format_routing_table_as_instructions", return_value="")
    def test_empty_configs(self, mock_routing):
        """Empty server configs produce base instructions only."""
        result = compile_instructions({})

        assert _BASE_INSTRUCTIONS in result
        assert "## Proactive Tool Usage" not in result


class TestCompileBehaviorLines:
    """Test behavior line compilation logic."""

    def test_hot_server_direct_reference(self):
        """HOT enabled server uses direct [name] reference."""
        configs = {
            "context7": _make_server(
                "context7",
                mode=ServerMode.HOT,
                enabled=True,
                behavior=BehaviorConfig(
                    triggers=["implementing with library"],
                    instruction="Lookup docs",
                    priority="high",
                ),
            ),
        }
        lines = _compile_behavior_lines(configs)

        assert len(lines) == 1
        assert "[context7]" in lines[0]
        assert "airis-exec" not in lines[0]

    def test_cold_server_airis_exec_reference(self):
        """COLD server uses airis-exec server:* reference."""
        configs = {
            "tavily": _make_server(
                "tavily",
                mode=ServerMode.COLD,
                enabled=True,
                behavior=BehaviorConfig(
                    triggers=["need current info"],
                    instruction="Search web",
                    priority="medium",
                ),
            ),
        }
        lines = _compile_behavior_lines(configs)

        assert len(lines) == 1
        assert "airis-exec tavily:*" in lines[0]

    def test_disabled_server_with_behavior_included(self):
        """Disabled servers with behavior are included (auto-enable via airis-exec)."""
        configs = {
            "sequential-thinking": _make_server(
                "sequential-thinking",
                mode=ServerMode.COLD,
                enabled=False,
                behavior=BehaviorConfig(
                    triggers=["complex analysis"],
                    instruction="Use sequential thinking",
                    priority="low",
                ),
            ),
        }
        lines = _compile_behavior_lines(configs)

        assert len(lines) == 1
        assert "airis-exec sequential-thinking:*" in lines[0]

    def test_priority_sorting(self):
        """Lines are sorted by priority: high > medium > low."""
        configs = {
            "low-server": _make_server(
                "low-server",
                behavior=BehaviorConfig(
                    triggers=["low trigger"],
                    instruction="Low action",
                    priority="low",
                ),
            ),
            "high-server": _make_server(
                "high-server",
                mode=ServerMode.HOT,
                behavior=BehaviorConfig(
                    triggers=["high trigger"],
                    instruction="High action",
                    priority="high",
                ),
            ),
            "medium-server": _make_server(
                "medium-server",
                behavior=BehaviorConfig(
                    triggers=["medium trigger"],
                    instruction="Medium action",
                    priority="medium",
                ),
            ),
        }
        lines = _compile_behavior_lines(configs)

        assert len(lines) == 3
        assert "High action" in lines[0]
        assert "Medium action" in lines[1]
        assert "Low action" in lines[2]

    def test_multiple_triggers_joined(self):
        """Multiple triggers are joined with ' / '."""
        configs = {
            "multi": _make_server(
                "multi",
                behavior=BehaviorConfig(
                    triggers=["trigger one", "trigger two"],
                    instruction="Do something",
                ),
            ),
        }
        lines = _compile_behavior_lines(configs)

        assert "trigger one / trigger two" in lines[0]

    def test_no_behavior_skipped(self):
        """Servers without behavior are skipped."""
        configs = {
            "no-behavior": _make_server("no-behavior"),
        }
        lines = _compile_behavior_lines(configs)

        assert len(lines) == 0

    def test_empty_triggers_skipped(self):
        """Behavior with empty triggers is skipped."""
        configs = {
            "empty": _make_server(
                "empty",
                behavior=BehaviorConfig(
                    triggers=[],
                    instruction="Do something",
                ),
            ),
        }
        lines = _compile_behavior_lines(configs)

        assert len(lines) == 0

    def test_empty_instruction_skipped(self):
        """Behavior with empty instruction is skipped."""
        configs = {
            "empty": _make_server(
                "empty",
                behavior=BehaviorConfig(
                    triggers=["some trigger"],
                    instruction="",
                ),
            ),
        }
        lines = _compile_behavior_lines(configs)

        assert len(lines) == 0
