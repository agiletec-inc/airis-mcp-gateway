"""Tests for build_toolset_index (issue #85)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from app.core.toolset_catalog import build_toolset_index


@dataclass
class _FakeConfig:
    tools_index: list[dict]


def _stub_seed_catalog(seed: dict | None = None):
    return patch("app.core.toolset_catalog._load_seed_catalog", return_value=seed or {})


def test_empty_configs_return_empty_index():
    with _stub_seed_catalog():
        assert build_toolset_index({}) == {}


def test_server_without_tools_index_is_skipped():
    configs = {"lonely": _FakeConfig(tools_index=[])}
    with _stub_seed_catalog():
        assert build_toolset_index(configs) == {}


def test_seed_catalog_populates_named_toolset():
    configs = {
        "stripe": _FakeConfig(
            tools_index=[
                {"name": "create_payment"},
                {"name": "list_charges"},
                {"name": "refund"},
            ]
        )
    }
    seed = {
        "stripe": {
            "toolsets": {
                "payments": {
                    "summary": "Payment operations",
                    "tools": ["create_payment", "refund"],
                }
            }
        }
    }
    with _stub_seed_catalog(seed):
        result = build_toolset_index(configs)

    assert "stripe.payments" in result
    payments = result["stripe.payments"]
    assert payments.server == "stripe"
    assert payments.name == "payments"
    assert payments.summary == "Payment operations"
    assert sorted(payments.tools) == ["create_payment", "refund"]


def test_remaining_tools_fall_into_default_toolset():
    configs = {
        "stripe": _FakeConfig(
            tools_index=[
                {"name": "create_payment"},
                {"name": "list_charges"},
                {"name": "refund"},
            ]
        )
    }
    seed = {
        "stripe": {
            "toolsets": {
                "payments": {
                    "summary": "Payment operations",
                    "tools": ["create_payment", "refund"],
                }
            }
        }
    }
    with _stub_seed_catalog(seed):
        result = build_toolset_index(configs)

    assert "stripe.default" in result
    default = result["stripe.default"]
    assert default.tools == ["list_charges"]
    assert default.summary == "Default capability slice for stripe"


def test_server_with_no_seed_entry_gets_default_only():
    configs = {
        "github": _FakeConfig(
            tools_index=[{"name": "get_issue"}, {"name": "list_prs"}]
        )
    }
    with _stub_seed_catalog({}):
        result = build_toolset_index(configs)

    assert list(result.keys()) == ["github.default"]
    assert result["github.default"].tools == ["get_issue", "list_prs"]


def test_tools_outside_indexed_list_are_ignored_from_seed():
    configs = {
        "stripe": _FakeConfig(tools_index=[{"name": "create_payment"}])
    }
    seed = {
        "stripe": {
            "toolsets": {
                "payments": {
                    "summary": "Payment operations",
                    # ghost_tool doesn't exist in tools_index — should be dropped.
                    "tools": ["create_payment", "ghost_tool"],
                }
            }
        }
    }
    with _stub_seed_catalog(seed):
        result = build_toolset_index(configs)

    assert result["stripe.payments"].tools == ["create_payment"]


def test_toolsets_with_no_matching_tools_are_skipped():
    configs = {
        "stripe": _FakeConfig(tools_index=[{"name": "create_payment"}])
    }
    seed = {
        "stripe": {
            "toolsets": {
                "refunds": {"summary": "refund-only", "tools": ["issue_refund"]},
            }
        }
    }
    with _stub_seed_catalog(seed):
        result = build_toolset_index(configs)

    # "refunds" has no overlap with tools_index so it should not be emitted,
    # but the single remaining tool should land in default.
    assert "stripe.refunds" not in result
    assert "stripe.default" in result
    assert result["stripe.default"].tools == ["create_payment"]
