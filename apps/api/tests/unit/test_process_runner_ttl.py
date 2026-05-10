"""
Tests for ProcessRunner adaptive TTL calculation and idle reaper behavior.
"""
import asyncio
import pytest
from app.core.process_runner import ProcessRunner, ProcessConfig


def test_adaptive_ttl_with_zero_window():
    """Test that TTL calculation handles zero window gracefully (no division by zero)."""
    config = ProcessConfig(
        name="test-server",
        command="echo",
        args=["test"],
        ttl_window=0,  # This could cause division by zero
        adaptive_ttl_enabled=True,
        min_ttl=30,
        max_ttl=300,
    )

    runner = ProcessRunner(config)

    # Should not raise ZeroDivisionError
    ttl = runner._calculate_adaptive_ttl()

    # Should return a valid TTL value
    assert ttl >= config.min_ttl
    assert ttl <= config.max_ttl


def test_adaptive_ttl_with_negative_window():
    """Test that TTL calculation handles negative window gracefully."""
    config = ProcessConfig(
        name="test-server",
        command="echo",
        args=["test"],
        ttl_window=-100,  # Invalid value
        adaptive_ttl_enabled=True,
        min_ttl=30,
        max_ttl=300,
    )

    runner = ProcessRunner(config)

    # Should not raise any error
    ttl = runner._calculate_adaptive_ttl()

    # Should return a valid TTL value
    assert ttl >= config.min_ttl
    assert ttl <= config.max_ttl


def test_adaptive_ttl_disabled():
    """Test that when adaptive TTL is disabled, base idle_timeout is returned."""
    config = ProcessConfig(
        name="test-server",
        command="echo",
        args=["test"],
        idle_timeout=120,
        adaptive_ttl_enabled=False,
    )

    runner = ProcessRunner(config)
    ttl = runner._calculate_adaptive_ttl()

    assert ttl == 120


def test_adaptive_ttl_normal_operation():
    """Test normal adaptive TTL calculation."""
    config = ProcessConfig(
        name="test-server",
        command="echo",
        args=["test"],
        ttl_window=300,
        adaptive_ttl_enabled=True,
        min_ttl=30,
        max_ttl=300,
    )

    runner = ProcessRunner(config)

    # With no calls, should return min_ttl
    ttl = runner._calculate_adaptive_ttl()
    assert ttl == config.min_ttl


@pytest.mark.asyncio
async def test_idle_reaper_skips_hot_servers():
    """HOT servers must never be idle-killed."""
    config = ProcessConfig(
        name="hot-server",
        command="echo",
        args=["test"],
        mode="hot",
        idle_timeout=1,  # Very short TTL
    )

    runner = ProcessRunner(config)
    # _idle_reaper should return immediately for HOT servers
    # (no infinite loop, no stop call)
    await asyncio.wait_for(runner._idle_reaper(), timeout=2.0)


@pytest.mark.asyncio
async def test_idle_reaper_runs_for_cold_servers():
    """COLD servers should have an active idle reaper."""
    config = ProcessConfig(
        name="cold-server",
        command="echo",
        args=["test"],
        mode="cold",
        idle_timeout=1,
    )

    runner = ProcessRunner(config)
    # For a stopped server, the reaper loop should exit quickly
    # (state is STOPPED by default, loop condition fails)
    await asyncio.wait_for(runner._idle_reaper(), timeout=2.0)
