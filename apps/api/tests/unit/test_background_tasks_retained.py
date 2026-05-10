"""
Regression test for issue #110: module-level asyncio.create_task references
not retained (GC risk).

Python's asyncio.create_task() only holds a weak reference to the task from
the event loop. If the caller drops its reference to the returned Task, a
garbage collection cycle can collect it mid-execution, causing the coroutine
to stop running silently. cfd32ec0 introduced `_background_tasks: set` in
app.main to hold strong references for the lifetime of each task.

These tests exercise the real `_spawn_background_task` helper against a real
event loop — no mocks. They verify:

1. A task spawned via the helper is present in `_background_tasks` while it
   is running.
2. The task is removed from `_background_tasks` after it completes (so the
   set does not leak tasks forever).
3. The GC cannot collect the task even when the caller throws away the
   returned reference — because the module-level set still holds it.
"""
from __future__ import annotations

import asyncio
import gc

import pytest

from app.main import _background_tasks, _spawn_background_task


@pytest.fixture(autouse=True)
def clear_background_tasks():
    _background_tasks.clear()
    yield
    _background_tasks.clear()


@pytest.mark.asyncio
async def test_spawn_background_task_adds_to_set():
    async def _worker():
        await asyncio.sleep(0.05)
        return "done"

    task = _spawn_background_task(_worker(), name="test_worker")
    assert task in _background_tasks
    assert len(_background_tasks) == 1

    result = await task
    assert result == "done"


@pytest.mark.asyncio
async def test_spawn_background_task_discards_after_completion():
    async def _worker():
        return 42

    task = _spawn_background_task(_worker(), name="test_worker")
    await task
    # done_callback runs on the next event loop iteration; yield control so it
    # can fire before we assert.
    await asyncio.sleep(0)
    assert task not in _background_tasks
    assert len(_background_tasks) == 0


@pytest.mark.asyncio
async def test_background_task_survives_gc_without_caller_reference():
    """The whole point of the set: if the caller drops its reference, the task
    must still run to completion. Without the strong reference in
    _background_tasks, gc.collect() could finalize the task mid-flight.
    """
    completion_marker: list[bool] = []

    async def _worker():
        # Give GC a chance to run before we finish.
        await asyncio.sleep(0.05)
        completion_marker.append(True)

    # Spawn and immediately discard the caller-side reference.
    _spawn_background_task(_worker(), name="gc_test_worker")

    # Trigger GC aggressively while the task is still in flight.
    gc.collect()
    await asyncio.sleep(0.01)
    gc.collect()

    # Wait for the task to finish. We recover it via the module-level set; if
    # GC had collected it, the set would be empty and this would fail.
    assert _background_tasks, "task was dropped before completion — GC risk"
    task = next(iter(_background_tasks))
    await task

    assert completion_marker == [True]


@pytest.mark.asyncio
async def test_on_error_callback_receives_task_on_failure():
    """The on_error callback hook is how the lifespan wires up error
    reporting for precache etc. Verify it fires with the task as its arg.
    """
    captured: list[asyncio.Task] = []

    def _on_error(task: asyncio.Task):
        captured.append(task)

    async def _worker():
        raise RuntimeError("boom")

    task = _spawn_background_task(
        _worker(),
        name="failing_worker",
        on_error=_on_error,
    )

    with pytest.raises(RuntimeError, match="boom"):
        await task

    # done_callback fires on the next loop iteration.
    await asyncio.sleep(0)
    assert captured == [task]
