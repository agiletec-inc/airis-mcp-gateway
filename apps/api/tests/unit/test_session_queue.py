"""
Tests for session response queue thread safety.
"""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_session_queue_concurrent_access():
    """Test that concurrent access to session queues is thread-safe."""
    # Import here to get fresh module state
    from app.api.endpoints.session_queue import (
        get_response_queue,
        remove_response_queue,
        _session_response_queues,
    )

    # Clear any existing state
    _session_response_queues.clear()

    session_ids = [f"session_{i}" for i in range(10)]

    # Concurrently create queues
    async def create_queue(session_id: str):
        queue = await get_response_queue(session_id)
        await queue.put({"session": session_id})
        return session_id

    results = await asyncio.gather(*[create_queue(sid) for sid in session_ids])

    assert len(results) == 10
    assert len(_session_response_queues) == 10

    # Verify each queue has the correct data
    for sid in session_ids:
        queue = await get_response_queue(sid)
        data = await queue.get()
        assert data["session"] == sid


@pytest.mark.asyncio
async def test_session_queue_concurrent_remove():
    """Test that concurrent removal of session queues is thread-safe."""
    from app.api.endpoints.session_queue import (
        get_response_queue,
        remove_response_queue,
        _session_response_queues,
    )

    # Clear any existing state
    _session_response_queues.clear()

    session_ids = [f"session_{i}" for i in range(10)]

    # Create all queues first
    for sid in session_ids:
        await get_response_queue(sid)

    assert len(_session_response_queues) == 10

    # Concurrently remove queues
    await asyncio.gather(*[remove_response_queue(sid) for sid in session_ids])

    assert len(_session_response_queues) == 0


@pytest.mark.asyncio
async def test_session_queue_get_creates_if_not_exists():
    """Test that get_response_queue creates queue if it doesn't exist."""
    from app.api.endpoints.session_queue import (
        get_response_queue,
        _session_response_queues,
    )

    # Clear any existing state
    _session_response_queues.clear()

    session_id = "new_session"
    assert session_id not in _session_response_queues

    queue = await get_response_queue(session_id)

    assert session_id in _session_response_queues
    assert isinstance(queue, asyncio.Queue)


@pytest.mark.asyncio
async def test_session_queue_remove_nonexistent():
    """Test that removing a nonexistent queue doesn't raise an error."""
    from app.api.endpoints.session_queue import (
        remove_response_queue,
        _session_response_queues,
    )

    # Clear any existing state
    _session_response_queues.clear()

    # Should not raise
    await remove_response_queue("nonexistent_session")

    assert len(_session_response_queues) == 0
