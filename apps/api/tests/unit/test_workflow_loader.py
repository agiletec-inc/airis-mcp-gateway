"""
Unit tests for Workflow Loader.

Tests cover:
- YAML parsing and WorkflowConfig creation
- Validation: required fields, invalid priority, kebab-case
- Priority sorting (high > medium > low, then filename)
- Missing/empty workflows directory handling
"""

import pytest
from pathlib import Path

from app.core.workflow_loader import (
    WorkflowConfig,
    load_workflows,
    _validate,
)


class TestValidate:
    """Test workflow validation logic."""

    def _make_valid(self, **overrides) -> WorkflowConfig:
        defaults = {
            "name": "test-workflow",
            "compile_to": "mcp_instructions",
            "priority": "high",
            "text": "WHEN test: do something",
            "servers": ["context7"],
        }
        defaults.update(overrides)
        return WorkflowConfig(**defaults)

    def test_valid_workflow_no_errors(self):
        errors = _validate(self._make_valid())
        assert errors == []

    def test_missing_name(self):
        errors = _validate(self._make_valid(name=""))
        assert any("name" in e for e in errors)

    def test_invalid_name_not_kebab_case(self):
        errors = _validate(self._make_valid(name="NotKebab"))
        assert any("kebab-case" in e for e in errors)

    def test_name_with_underscores_rejected(self):
        errors = _validate(self._make_valid(name="my_workflow"))
        assert any("kebab-case" in e for e in errors)

    def test_invalid_priority(self):
        errors = _validate(self._make_valid(priority="critical"))
        assert any("priority" in e for e in errors)

    def test_missing_compile_to(self):
        errors = _validate(self._make_valid(compile_to=""))
        assert any("compile_to" in e for e in errors)

    def test_empty_text(self):
        errors = _validate(self._make_valid(text=""))
        assert any("text" in e for e in errors)

    def test_whitespace_only_text(self):
        errors = _validate(self._make_valid(text="   \n  "))
        assert any("text" in e for e in errors)

    def test_multiple_errors_reported(self):
        """Multiple validation errors are all reported."""
        errors = _validate(self._make_valid(
            name="",
            priority="invalid",
            compile_to="",
            text="",
        ))
        assert len(errors) >= 3


class TestLoadWorkflows:
    """Test workflow loading from directory."""

    def test_load_from_directory(self, tmp_path):
        """Valid YAML files are loaded and sorted."""
        (tmp_path / "b-second.yaml").write_text(
            "name: b-second\n"
            "compile_to: mcp_instructions\n"
            "priority: medium\n"
            "servers: [tavily]\n"
            "text: WHEN test B\n"
        )
        (tmp_path / "a-first.yaml").write_text(
            "name: a-first\n"
            "compile_to: mcp_instructions\n"
            "priority: high\n"
            "servers: [context7]\n"
            "text: WHEN test A\n"
        )

        workflows = load_workflows(tmp_path)

        assert len(workflows) == 2
        assert workflows[0].name == "a-first"  # high priority first
        assert workflows[1].name == "b-second"  # medium after high

    def test_same_priority_sorted_by_filename(self, tmp_path):
        """Same priority workflows are sorted by filename."""
        (tmp_path / "z-last.yaml").write_text(
            "name: z-last\n"
            "compile_to: mcp_instructions\n"
            "priority: high\n"
            "servers: [s1]\n"
            "text: WHEN test Z\n"
        )
        (tmp_path / "a-first.yaml").write_text(
            "name: a-first\n"
            "compile_to: mcp_instructions\n"
            "priority: high\n"
            "servers: [s2]\n"
            "text: WHEN test A\n"
        )

        workflows = load_workflows(tmp_path)

        assert len(workflows) == 2
        assert workflows[0].name == "a-first"
        assert workflows[1].name == "z-last"

    def test_invalid_yaml_skipped(self, tmp_path):
        """Invalid YAML files are skipped with error log."""
        (tmp_path / "bad.yaml").write_text("{{invalid yaml")
        (tmp_path / "good.yaml").write_text(
            "name: good\n"
            "compile_to: mcp_instructions\n"
            "priority: high\n"
            "servers: [s1]\n"
            "text: WHEN test\n"
        )

        workflows = load_workflows(tmp_path)

        assert len(workflows) == 1
        assert workflows[0].name == "good"

    def test_validation_error_skipped(self, tmp_path):
        """Workflow with validation errors is skipped."""
        (tmp_path / "bad.yaml").write_text(
            "name: BadName\n"  # Not kebab-case
            "compile_to: mcp_instructions\n"
            "priority: high\n"
            "servers: [s1]\n"
            "text: WHEN test\n"
        )

        workflows = load_workflows(tmp_path)
        assert len(workflows) == 0

    def test_nonexistent_directory_returns_empty(self):
        """Non-existent directory returns empty list."""
        workflows = load_workflows(Path("/nonexistent/path"))
        assert workflows == []

    def test_empty_directory_returns_empty(self, tmp_path):
        """Empty directory returns empty list."""
        workflows = load_workflows(tmp_path)
        assert workflows == []

    def test_non_yaml_files_ignored(self, tmp_path):
        """Non-YAML files are ignored."""
        (tmp_path / "README.md").write_text("# Not a workflow")
        (tmp_path / "good.yaml").write_text(
            "name: good\n"
            "compile_to: mcp_instructions\n"
            "priority: high\n"
            "servers: [s1]\n"
            "text: WHEN test\n"
        )

        workflows = load_workflows(tmp_path)
        assert len(workflows) == 1

    def test_servers_default_to_empty_list(self, tmp_path):
        """Servers field defaults to empty list (but fails validation)."""
        (tmp_path / "no-servers.yaml").write_text(
            "name: no-servers\n"
            "compile_to: mcp_instructions\n"
            "priority: high\n"
            "text: WHEN test\n"
        )

        # No servers field → passes parsing but servers=[]
        # _validate does NOT require servers, so it loads
        workflows = load_workflows(tmp_path)
        assert len(workflows) == 1
        assert workflows[0].servers == []

    def test_compile_to_filter(self, tmp_path):
        """Workflows with any compile_to value are loaded (filtering is in compiler)."""
        (tmp_path / "wf.yaml").write_text(
            "name: wf\n"
            "compile_to: mcp_instructions\n"
            "priority: high\n"
            "text: test text\n"
        )

        workflows = load_workflows(tmp_path)
        assert len(workflows) == 1
        assert workflows[0].compile_to == "mcp_instructions"
