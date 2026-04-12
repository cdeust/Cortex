"""Tests for mcp_server.core.write_post_store — engram slot allocation + cache."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mcp_server.core.write_post_store import (
    allocate_engram_slot,
    invalidate_slot_cache,
    _get_slot_cache,
    _update_slot_cache,
)


def _make_settings(**overrides):
    defaults = {
        "HOPFIELD_MAX_PATTERNS": 5,
        "EXCITABILITY_HALF_LIFE_HOURS": 6.0,
        "EXCITABILITY_BOOST": 0.5,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_store(slots=None, memories_in_slot=0):
    """Build a mock store with sensible defaults."""
    now = datetime.now(timezone.utc).isoformat()
    if slots is None:
        slots = [
            {"slot_index": 0, "excitability": 0.3, "last_activated": now},
            {"slot_index": 1, "excitability": 0.9, "last_activated": now},
            {"slot_index": 2, "excitability": 0.1, "last_activated": now},
        ]
    store = MagicMock()
    store.get_all_engram_slots.return_value = slots
    store.count_memories_in_slot.return_value = memories_in_slot
    store._now_iso.return_value = now
    return store


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure slot cache is clean before and after each test."""
    invalidate_slot_cache()
    yield
    invalidate_slot_cache()


# ── allocate_engram_slot ─────────────────────────────────────────────


class TestAllocateEngramSlot:
    def test_picks_most_excitable_slot(self):
        store = _make_store()
        settings = _make_settings()
        result = allocate_engram_slot(mem_id=42, settings=settings, store=store)
        assert result is not None
        # Slot 1 has highest excitability (0.9)
        assert result["slot_index"] == 1
        store.assign_memory_slot.assert_called_once_with(42, 1)

    def test_returns_none_when_no_slots(self):
        store = _make_store(slots=[])
        result = allocate_engram_slot(
            mem_id=1,
            settings=_make_settings(),
            store=store,
        )
        assert result is None

    def test_temporally_linked_excludes_current_memory(self):
        """The count must exclude mem_id — this is why we pass exclude_id."""
        store = _make_store(memories_in_slot=3)
        result = allocate_engram_slot(
            mem_id=99,
            settings=_make_settings(),
            store=store,
        )
        assert result is not None
        # count_memories_in_slot is called with exclude_id=mem_id
        store.count_memories_in_slot.assert_called_once()
        call_kwargs = store.count_memories_in_slot.call_args
        assert call_kwargs.kwargs.get("exclude_id") == 99
        # The returned count should be the raw count (already excluded)
        assert result["temporally_linked"] == 3

    def test_temporally_linked_zero_when_empty_slot(self):
        store = _make_store(memories_in_slot=0)
        result = allocate_engram_slot(
            mem_id=1,
            settings=_make_settings(),
            store=store,
        )
        assert result is not None
        assert result["temporally_linked"] == 0

    def test_exception_returns_none(self):
        store = _make_store()
        store.get_all_engram_slots.side_effect = RuntimeError("db down")
        # Cache must be clear so it actually calls get_all_engram_slots
        invalidate_slot_cache()
        result = allocate_engram_slot(
            mem_id=1,
            settings=_make_settings(),
            store=store,
        )
        assert result is None

    def test_updates_excitability_in_db(self):
        store = _make_store()
        allocate_engram_slot(mem_id=1, settings=_make_settings(), store=store)
        store.update_engram_slot.assert_called_once()
        args = store.update_engram_slot.call_args[0]
        # Slot 1 wins, new_exc = min(0.9 * decay + 0.5, 1.0)
        assert args[0] == 1  # slot_index
        assert 0.0 < args[1] <= 1.0  # new excitability


# ── Slot cache ────────────────────────────────────────────────────────


class TestSlotCache:
    def test_cache_populated_on_first_call(self):
        store = _make_store()
        slots = _get_slot_cache(store, num_slots=5)
        assert len(slots) == 3
        store.init_engram_slots.assert_called_once_with(5)
        store.get_all_engram_slots.assert_called_once()

    def test_cache_reused_on_second_call(self):
        store = _make_store()
        _get_slot_cache(store, num_slots=5)
        _get_slot_cache(store, num_slots=5)
        # Only fetched once despite two calls
        assert store.get_all_engram_slots.call_count == 1

    def test_cache_invalidated_on_new_store(self):
        store1 = _make_store()
        store2 = _make_store()
        _get_slot_cache(store1, num_slots=5)
        _get_slot_cache(store2, num_slots=5)
        # Each store triggers its own fetch
        assert store1.get_all_engram_slots.call_count == 1
        assert store2.get_all_engram_slots.call_count == 1

    def test_invalidate_forces_refetch(self):
        store = _make_store()
        _get_slot_cache(store, num_slots=5)
        invalidate_slot_cache()
        _get_slot_cache(store, num_slots=5)
        assert store.get_all_engram_slots.call_count == 2

    def test_update_slot_cache_modifies_in_place(self):
        now = datetime.now(timezone.utc).isoformat()
        store = _make_store()
        slots = _get_slot_cache(store, num_slots=5)
        original_exc = slots[1]["excitability"]  # slot_index=1
        _update_slot_cache(1, 0.42, now)
        # The cached list is mutated in place
        assert slots[1]["excitability"] == 0.42
        assert slots[1]["last_activated"] == now
        assert original_exc != 0.42

    def test_update_nonexistent_slot_is_noop(self):
        store = _make_store()
        _get_slot_cache(store, num_slots=5)
        # Slot 999 doesn't exist — should not raise
        _update_slot_cache(999, 0.5, "2024-01-01T00:00:00Z")

    def test_update_before_cache_init_is_noop(self):
        # Cache not yet populated — should not raise
        _update_slot_cache(0, 0.5, "2024-01-01T00:00:00Z")
