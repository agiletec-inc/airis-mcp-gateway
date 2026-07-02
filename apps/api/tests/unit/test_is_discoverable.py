"""Tests for is_discoverable() (issue #193 review).

is_discoverable() is the single predicate shared by every discovery index
seeding site (dynamic_mcp.refresh_cache_hot_only, toolset_catalog.build_toolset_index,
mcp_proxy.handle_airis_find fallback, dynamic_mcp.build_compact_tool_listing
fallback). Only `policy_disabled` servers (never authorized to run, e.g.
supabase, mindbase) are excluded — plain `enabled: false` COLD/lazy servers
(e.g. stripe) remain discoverable.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.mcp_config_loader import is_discoverable


@dataclass
class _FakeConfig:
    policy_disabled: bool = False


def test_default_config_is_discoverable():
    assert is_discoverable(_FakeConfig()) is True


def test_policy_disabled_config_is_not_discoverable():
    assert is_discoverable(_FakeConfig(policy_disabled=True)) is False


def test_config_missing_policy_disabled_attr_is_discoverable():
    """Objects without the attribute at all (e.g. a stale/duck-typed config)
    must default to discoverable — matches the dataclass field default."""

    class _NoAttr:
        pass

    assert is_discoverable(_NoAttr()) is True
