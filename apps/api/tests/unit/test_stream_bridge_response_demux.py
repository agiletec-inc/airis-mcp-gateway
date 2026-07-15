"""Reproduce issue #210: response demux drops out-of-order concurrent replies.

``StreamBridgeSession`` holds a single shared ``response_queue``. When two
``send_via_stream_bridge()`` calls run concurrently against the same session
(two ``tools/call`` requests sharing one ``Mcp-Session-Id``), each awaits
``session.response_queue.get()`` in a loop looking for the JSON-RPC response
whose ``id`` matches its own ``expected_id``.

A payload that HAS an ``id`` but belongs to the OTHER concurrent call
(``id != expected_id``) matches neither:

* the "is my response" branch (`expected_id is None or get_response_message_id(payload) == expected_id`)
* nor the "is a notification" branch (`"method" in payload and "id" not in payload`)

so it falls through the ``while True`` loop and is silently dropped forever —
never requeued for the caller that actually owns it. That caller then blocks
until ``settings.TOOL_CALL_TIMEOUT`` and returns a 504, even though the
Gateway already answered.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.api.endpoints import gateway_stream_bridge
from app.core.config import settings


class _FakeHeaders(dict):
    def get(self, key, default=None):  # noqa: D401 - dict.get shadow for Request-like API
        return super().get(key, default)


class _FakeRequest:
    """Minimal stand-in exposing only what get_stream_session_id() touches."""

    def __init__(self, session_id: str):
        self.headers = _FakeHeaders({gateway_stream_bridge.stream_session_header_name(): session_id})


class _FakeGatewayResponse:
    def __init__(self, status_code: int = 202):
        self.status_code = status_code
        self.text = ""
        self.headers: dict = {}


class _FakeGatewayClient:
    """Stands in for httpx.AsyncClient — the POST is accepted (202), the
    actual JSON-RPC response arrives later via the shared response_queue,
    exactly like the real Gateway's SSE-fan-out flow."""

    async def post(self, *args, **kwargs):
        return _FakeGatewayResponse(status_code=202)


@pytest.fixture(autouse=True)
def clear_bridge_state():
    gateway_stream_bridge._stream_bridge_sessions.clear()
    yield
    gateway_stream_bridge._stream_bridge_sessions.clear()


def _make_session(public_session_id: str) -> gateway_stream_bridge.StreamBridgeSession:
    return gateway_stream_bridge.StreamBridgeSession(
        public_session_id=public_session_id,
        backend_session_id="backend-session-xyz",
        client=_FakeGatewayClient(),
        stream_context=object(),
        stream_response=object(),
        # Session "born" long ago so send_via_stream_bridge() skips the
        # STREAM_BRIDGE_READY_DELAY settle-sleep for both callers. Without
        # this, the two callers' sleep durations differ by the few
        # microseconds between their monotonic() reads, which flips which
        # one reaches the response_queue first and can mask the race this
        # test targets.
        created_at=0.0,
    )


@pytest.mark.asyncio
async def test_concurrent_calls_each_get_their_own_response(monkeypatch):
    """Two concurrent tools/call requests on ONE shared session must each
    receive their own matching JSON-RPC response — not a 504 timeout and
    not the other call's payload — even when the Gateway answers out of
    order (id=2's answer lands on the shared queue before id=1's).

    In production, a response can only reach the shared queue after a real
    Gateway round trip (this call's own POST lands, the Gateway processes
    it, its SSE reader forwards the answer) — which always takes longer
    than the synchronous work needed to register as a waiter. So the
    responses are injected here only once BOTH callers have registered
    (visible via `session.pending_response_ids`), matching that ordering
    instead of racing it against a zero-latency fake POST."""
    monkeypatch.setattr(settings, "TOOL_CALL_TIMEOUT", 1.0)

    session = _make_session("airis-demux-test")
    gateway_stream_bridge._stream_bridge_sessions[session.public_session_id] = session

    request = _FakeRequest(session.public_session_id)

    task_a = asyncio.create_task(
        gateway_stream_bridge.send_via_stream_bridge(
            request, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "a"}}
        )
    )
    task_b = asyncio.create_task(
        gateway_stream_bridge.send_via_stream_bridge(
            request, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "b"}}
        )
    )

    for _ in range(200):
        if {1, 2} <= session.pending_response_ids.keys():
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("both callers never registered as live waiters")

    # Now simulate the Gateway answering call B (id=2) before call A
    # (id=1), e.g. because B's tool happened to resolve faster server-side.
    await session.response_queue.put({"jsonrpc": "2.0", "id": 2, "result": {"for": "B"}})
    await session.response_queue.put({"jsonrpc": "2.0", "id": 1, "result": {"for": "A"}})

    response_a, response_b = await asyncio.gather(task_a, task_b)

    body_a = json.loads(response_a.body)
    body_b = json.loads(response_b.body)

    assert response_a.status_code == 200, (
        f"caller A (id=1) did not get its response: status={response_a.status_code} body={body_a}"
    )
    assert response_b.status_code == 200, (
        f"caller B (id=2) did not get its response: status={response_b.status_code} body={body_b}"
    )
    assert body_a.get("id") == 1
    assert body_a.get("result") == {"for": "A"}
    assert body_b.get("id") == 2
    assert body_b.get("result") == {"for": "B"}


@pytest.mark.asyncio
async def test_orphaned_response_is_dropped_not_requeued_forever(monkeypatch):
    """A response for an id nobody is waiting for anymore (its own caller
    already timed out / disconnected before the Gateway's late answer
    arrived) must be dropped, not requeued forever — requeuing it back
    onto the same queue that the sole remaining reader is draining, with
    no live owner ever going to claim it, would spin that reader in a
    synchronous busy loop instead of letting its own wait_for() timeout
    ever fire. This test has no live claimant for id=999 at all — the call
    under test (id=1) must still reach its own 504 timeout promptly."""
    monkeypatch.setattr(settings, "TOOL_CALL_TIMEOUT", 1.0)

    session = _make_session("airis-demux-orphan-test")
    gateway_stream_bridge._stream_bridge_sessions[session.public_session_id] = session

    # id=999 belongs to a call that is no longer live (e.g. already timed
    # out or disconnected) — nobody is or ever will be waiting for it, so
    # it's never in session.pending_response_ids.
    await session.response_queue.put({"jsonrpc": "2.0", "id": 999, "result": {"for": "ghost"}})

    request = _FakeRequest(session.public_session_id)

    # If the orphan were requeued unconditionally, this would hang forever
    # (a synchronous get/put spin with no other reader). The outer
    # asyncio.wait_for is a test-level safety net, not the mechanism under
    # test — the real assertion is the prompt 504 below.
    response_a = await asyncio.wait_for(
        gateway_stream_bridge.send_via_stream_bridge(
            request, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "a"}}
        ),
        timeout=5.0,
    )

    body_a = json.loads(response_a.body)
    assert response_a.status_code == 504, (
        f"expected a prompt timeout once the orphan is dropped, "
        f"got status={response_a.status_code} body={body_a}"
    )
    # The orphan must have been dropped, not left sitting in the queue forever.
    assert session.response_queue.empty()


@pytest.mark.asyncio
async def test_many_concurrent_callers_all_get_correct_responses(monkeypatch):
    """Regression guard for a fixed-retry-count design that was tried and
    rejected during #210's review: bouncing a foreign-id payload only a
    fixed number of times (e.g. 5) before dropping it works for a couple
    of concurrent callers, but incorrectly drops a still-live sibling's
    response as "orphaned" once there are more concurrent callers than the
    threshold — because a fixed count can't distinguish "several live
    bystanders churning the queue" from "no owner left." The actual fix
    checks live-waiter membership instead, so this must hold for an
    arbitrarily large number of concurrent callers, not just two."""
    monkeypatch.setattr(settings, "TOOL_CALL_TIMEOUT", 2.0)

    session = _make_session("airis-demux-many-callers-test")
    gateway_stream_bridge._stream_bridge_sessions[session.public_session_id] = session

    request = _FakeRequest(session.public_session_id)

    ids = list(range(1, 9))  # 8 concurrent callers — more than any small fixed retry bound
    tasks = {
        i: asyncio.create_task(
            gateway_stream_bridge.send_via_stream_bridge(
                request,
                {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": f"call-{i}"}},
            )
        )
        for i in ids
    }

    for _ in range(200):
        if set(ids) <= session.pending_response_ids.keys():
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("not all callers registered as live waiters")

    # Deliver every answer in reverse id order — maximally out-of-order —
    # so each caller has to bounce through several foreign ids before its
    # own arrives.
    for i in reversed(ids):
        await session.response_queue.put({"jsonrpc": "2.0", "id": i, "result": {"for": i}})

    responses = await asyncio.gather(*(tasks[i] for i in ids))

    for i, response in zip(ids, responses):
        body = json.loads(response.body)
        assert response.status_code == 200, (
            f"caller id={i} did not get its response: status={response.status_code} body={body}"
        )
        assert body.get("id") == i
        assert body.get("result") == {"for": i}


@pytest.mark.asyncio
async def test_duplicate_id_caller_not_dropped_when_sibling_with_same_id_exits(monkeypatch):
    """Regression test for #215: `pending_response_ids` must be a refcount,
    not a plain set. If two concurrent callers on one session register the
    SAME id (a JSON-RPC id-uniqueness violation by the client, or
    coincidental id reuse across overlapping in-flight requests), the
    first of those callers to exit must NOT wipe the id's liveness out
    from under the second, still-waiting one — otherwise a bystander call
    dequeuing a foreign response for that id would misjudge it as
    orphaned and drop it, even though the second duplicate-id caller is
    still alive and will now spuriously time out despite the Gateway
    having answered.

    Sequence, with callers started in this exact order so asyncio.Queue's
    FIFO getter ordering is deterministic:
      1. caller_a (id=5) and caller_b (id=5) both register — refcount[5] == 2.
      2. caller_c (id=9, bystander) registers.
      3. First id=5 payload goes to caller_a (oldest waiter) -> it exits,
         refcount[5] 2 -> 1 (NOT removed, because caller_b is still live).
      4. Second id=5 payload goes to the next oldest waiter, caller_c
         (bystander) -> sees a foreign id, checks liveness, finds id=5
         still registered (thanks to caller_b) -> requeues instead of
         dropping. Under the old set-based design this membership check
         would have failed (caller_a's exit would have removed id 5
         entirely), and caller_b would then time out (504) despite the
         Gateway having answered.
      5. The requeued payload reaches caller_b (the only remaining id=5
         waiter) -> it exits with 200.
      6. caller_c's own id=9 payload arrives -> it exits with 200.
    """
    monkeypatch.setattr(settings, "TOOL_CALL_TIMEOUT", 2.0)

    session = _make_session("airis-demux-duplicate-id-test")
    gateway_stream_bridge._stream_bridge_sessions[session.public_session_id] = session

    request = _FakeRequest(session.public_session_id)

    def _call(call_id: int, tag: str):
        return asyncio.create_task(
            gateway_stream_bridge.send_via_stream_bridge(
                request,
                {"jsonrpc": "2.0", "id": call_id, "method": "tools/call", "params": {"name": tag}},
            )
        )

    # Start strictly in this order and let each fully register before the
    # next starts, so the queue's FIFO getter order matches this order.
    task_a = _call(5, "a")
    for _ in range(200):
        if session.pending_response_ids.get(5) == 1:
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("caller_a never registered")

    task_b = _call(5, "b")
    for _ in range(200):
        if session.pending_response_ids.get(5) == 2:
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("caller_b never registered (duplicate id refcount didn't reach 2)")

    task_c = _call(9, "c")
    for _ in range(200):
        if 9 in session.pending_response_ids:
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("caller_c never registered")

    # First id=5 answer -> consumed by the oldest waiter, caller_a.
    await session.response_queue.put({"jsonrpc": "2.0", "id": 5, "result": {"for": "a"}})
    done, _pending = await asyncio.wait({task_a}, timeout=5.0)
    assert task_a in done, "caller_a never completed"
    response_a = task_a.result()
    assert response_a.status_code == 200
    assert json.loads(response_a.body).get("result") == {"for": "a"}

    # The critical assertion: id=5 must still be registered (caller_b is
    # still live) — this is exactly what a set-based discard() would break.
    assert session.pending_response_ids.get(5) == 1, (
        "id=5 liveness was wiped out by caller_a's exit even though "
        "caller_b (same id) is still waiting"
    )

    # Second id=5 answer -> the next oldest waiter is caller_c (a
    # bystander expecting id=9). It must requeue this, not drop it.
    await session.response_queue.put({"jsonrpc": "2.0", "id": 5, "result": {"for": "b"}})
    done, _pending = await asyncio.wait({task_b}, timeout=5.0)
    assert task_b in done, (
        "caller_b never completed — its response was likely dropped as "
        "'orphaned' by bystander caller_c, exactly the #215 regression"
    )
    response_b = task_b.result()
    assert response_b.status_code == 200, (
        f"caller_b (duplicate id=5) did not get its response: "
        f"status={response_b.status_code} body={json.loads(response_b.body)}"
    )
    assert json.loads(response_b.body).get("result") == {"for": "b"}

    # Finally, caller_c's own answer.
    await session.response_queue.put({"jsonrpc": "2.0", "id": 9, "result": {"for": "c"}})
    response_c = await asyncio.wait_for(task_c, timeout=5.0)
    assert response_c.status_code == 200
    assert json.loads(response_c.body).get("result") == {"for": "c"}

    assert 5 not in session.pending_response_ids
    assert 9 not in session.pending_response_ids
