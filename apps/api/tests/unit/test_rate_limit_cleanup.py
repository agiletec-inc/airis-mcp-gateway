"""Tests for rate limit store cleanup and log key redaction (issue #102)."""

from __future__ import annotations

import time

from app.middleware.rate_limit import (
    RateLimitStore,
)


def test_cleanup_removes_expired_entries():
    store = RateLimitStore()
    store.check_and_increment("alice", limit=10, window=60)
    store.check_and_increment("bob", limit=10, window=60)

    # Age alice's entry past the window.
    store._store["alice"].window_start = time.time() - 120

    removed = store.cleanup_expired(window=60)

    assert removed == 1
    assert "alice" not in store._store
    assert "bob" in store._store


def test_cleanup_keeps_fresh_entries():
    store = RateLimitStore()
    store.check_and_increment("fresh", limit=10, window=60)

    removed = store.cleanup_expired(window=60)

    assert removed == 0
    assert "fresh" in store._store


def test_cleanup_on_empty_store_is_a_noop():
    store = RateLimitStore()
    assert store.cleanup_expired() == 0


def test_len_reports_entry_count():
    store = RateLimitStore()
    assert len(store) == 0
    store.check_and_increment("x", limit=1, window=60)
    store.check_and_increment("y", limit=1, window=60)
    assert len(store) == 2


def test_log_id_is_stable_and_does_not_leak_secret():
    key = "apikey:sk-live-supersecret"
    store = RateLimitStore()
    store.check_and_increment(key, limit=10)
    log_id = store.get_log_id(key)

    assert log_id == store.get_log_id(key)
    assert "supersecret" not in log_id
    assert len(log_id) == 12
