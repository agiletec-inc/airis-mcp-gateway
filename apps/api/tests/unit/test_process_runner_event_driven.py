"""
Regression test for issue #100: polling with asyncio.sleep(0.05) instead of
event-driven in ensure_ready.

f4646b45 replaced the 50ms polling loop with an asyncio.Condition. Any state
transition goes through `_set_state()` which notifies waiters, so
`ensure_ready_with_error` unblocks immediately when the process becomes READY
instead of waiting up to 50ms for the next poll.

These tests drive the real `ProcessRunner._state_cond` against a real event
loop — no mocks. The trick: we do not actually spawn a subprocess (that would
require a real MCP server). Instead we construct a ProcessRunner, then use
`_set_state()` to drive the state machine from another task, proving the
waiter unblocks on the condition's notify, not on a timer.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.process_runner import ProcessConfig, ProcessRunner, ProcessState


def _make_runner(name: str = "test") -> ProcessRunner:
    return ProcessRunner(
        ProcessConfig(
            name=name,
            command="echo",
            args=["hello"],
        )
    )


def test_runner_has_asyncio_condition_for_state_transitions():
    """Sanity: the Condition must be an asyncio.Condition, not a Lock or
    Event. Using the wrong primitive would reintroduce polling (a Lock has no
    notify_all) or miss notifications (Event.set is sticky)."""
    runner = _make_runner()
    assert isinstance(runner._state_cond, asyncio.Condition)


@pytest.mark.asyncio
async def test_set_state_notifies_waiters_immediately():
    """A task waiting on the condition must unblock as soon as _set_state
    fires — within a few milliseconds, not after the old 50ms poll window.
    """
    runner = _make_runner()
    runner._state = ProcessState.RUNNING

    async def waiter():
        async with runner._state_cond:
            # Mirrors the loop inside ensure_ready_with_error.
            while runner._state != ProcessState.READY:
                await runner._state_cond.wait()
        return time.monotonic()

    waiter_task = asyncio.create_task(waiter())
    # Yield once so the waiter has a chance to enter wait().
    await asyncio.sleep(0)

    start = time.monotonic()
    await runner._set_state(ProcessState.READY)
    # Hard-cap the wait so a regressed _set_state that forgets to call
    # notify_all() fails loudly instead of hanging the test runner forever.
    try:
        unblocked_at = await asyncio.wait_for(waiter_task, timeout=1.0)
    except asyncio.TimeoutError:
        waiter_task.cancel()
        pytest.fail(
            "waiter did not unblock within 1s after _set_state — "
            "Condition.notify_all() probably missing (issue #100)."
        )

    elapsed = unblocked_at - start
    # Pure event-driven unblock should take well under 20ms even on a loaded
    # CI box. The old 50ms polling implementation could not beat ~50ms worst
    # case, so a threshold of 25ms clearly distinguishes the two regimes.
    assert elapsed < 0.025, (
        f"waiter took {elapsed*1000:.1f}ms to unblock after _set_state; "
        "likely regressed to polling instead of Condition.notify_all "
        "(issue #100)."
    )


@pytest.mark.asyncio
async def test_multiple_waiters_all_wake_on_state_change():
    """notify_all must be used, not notify(), so every in-flight
    ensure_ready_with_error call sees the transition. If someone changed it
    to plain notify() only one waiter would unblock and the rest would hang
    until the next transition."""
    runner = _make_runner()
    runner._state = ProcessState.RUNNING

    woken = asyncio.Event()
    wake_count = 0

    async def waiter():
        nonlocal wake_count
        async with runner._state_cond:
            while runner._state != ProcessState.READY:
                await runner._state_cond.wait()
            wake_count += 1
            if wake_count == 3:
                woken.set()

    tasks = [asyncio.create_task(waiter()) for _ in range(3)]
    await asyncio.sleep(0)  # let them all enter wait()

    await runner._set_state(ProcessState.READY)

    await asyncio.wait_for(woken.wait(), timeout=0.5)
    for t in tasks:
        await t
    assert wake_count == 3


@pytest.mark.asyncio
async def test_ensure_ready_returns_immediately_when_already_ready():
    """Fast path: if state is already READY, no waiting at all."""
    runner = _make_runner()
    runner._state = ProcessState.READY

    start = time.monotonic()
    ok, err = await runner.ensure_ready_with_error(timeout=1.0)
    elapsed = time.monotonic() - start

    assert ok is True
    assert err is None
    assert elapsed < 0.01, (
        f"fast-path ensure_ready took {elapsed*1000:.1f}ms; it should return "
        "before any condition wait."
    )
