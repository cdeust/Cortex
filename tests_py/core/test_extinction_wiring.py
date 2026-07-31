"""Integration test for E2 fear-extinction wiring into reconsolidation +
active_forgetting, and the persisted extinction_strength column.

Verifies, against the real sqlite store (no Postgres required):
  - the extinction_strength column persists on written memories and round-trips;
  - update_memory_extinction writes ONLY the tag (heat/content untouched);
  - reconsolidation.compute_extinction_action grows the tag on deprecate,
    decays it on recover (spontaneous recovery), and clears it on reinstate —
    the association is suppressed WITHOUT deletion (Bouton 2004);
  - active_forgetting.should_extinguish offers extinction as a reversible
    alternative to the is_stale (permanent) delete circuit;
  - extinguished_count reports deprecated-but-retained memories;
  - CORTEX_ABLATE_EXTINCTION=1 fully disables the mechanism (no tag change).
"""

from __future__ import annotations

import os
import tempfile

import pytest

from mcp_server.core import active_forgetting
from mcp_server.core.reconsolidation import compute_extinction_action
from mcp_server.core import extinction as ext
import pathlib


@pytest.fixture()
def store():
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

    fd, path = tempfile.mkstemp(suffix=".db")

    os.close(fd)
    s = SqliteMemoryStore(path)
    yield s
    try:
        pathlib.Path(path).unlink()
    except OSError:
        pass


def _insert(store, content, **kw):
    data = {"content": content, "tags": []}
    data.update(kw)
    return store.insert_memory(data)


# ── Persistence + round-trip ─────────────────────────────────────────────────
def test_extinction_column_defaults_zero(store):
    mid = _insert(store, "a plain memory")
    row = store.get_memory(mid)
    assert row["extinction_strength"] == pytest.approx(0.0)


def test_extinction_column_persists_on_insert(store):
    mid = _insert(store, "a deprecated memory", extinction_strength=0.7)
    row = store.get_memory(mid)
    assert row["extinction_strength"] == pytest.approx(0.7)


def test_update_memory_extinction_round_trips(store):
    mid = _insert(store, "will be deprecated")
    store.update_memory_extinction(mid, 0.6)
    row = store.get_memory(mid)
    assert row["extinction_strength"] == pytest.approx(0.6)


def test_update_extinction_leaves_heat_and_content(store):
    mid = _insert(store, "content stays", heat=0.9)
    before = store.get_memory(mid)
    store.update_memory_extinction(mid, 0.8)
    after = store.get_memory(mid)
    # Only the tag moved — this is suppression, not erasure.
    assert after["content"] == before["content"]
    assert after["heat_base"] == pytest.approx(before["heat_base"])
    assert after["extinction_strength"] == pytest.approx(0.8)


def test_update_extinction_clamps(store):
    mid = _insert(store, "clamp me")
    store.update_memory_extinction(mid, 5.0)
    assert store.get_memory(mid)["extinction_strength"] == pytest.approx(1.0)


# ── extinguished_count read side ─────────────────────────────────────────────
def test_extinguished_count(store):
    a = _insert(store, "kept")
    b = _insert(store, "deprecated one")
    c = _insert(store, "deprecated two")
    store.update_memory_extinction(b, 0.7)
    store.update_memory_extinction(c, 0.9)
    assert store.extinguished_count() == 2
    # a is untouched (tag 0) -> not counted
    store.update_memory_extinction(a, 0.1)
    assert store.extinguished_count() == 2  # below default 0.5 threshold


# ── reconsolidation bridge: deprecate / recover / reinstate ──────────────────
def test_deprecate_grows_tag_no_delete(store):
    mid = _insert(store, "reversibly suppressed", heat=0.8)
    mem = store.get_memory(mid)
    out = compute_extinction_action(mem, operation="deprecate", trials=1)
    assert out.action == "none"  # never re-stores content
    assert out.extinction_strength == pytest.approx(ext.EXTINCTION_TRIAL_GAIN)
    store.update_memory_extinction(mid, out.extinction_strength)
    row = store.get_memory(mid)
    # Memory still present; only effective strength suppressed.
    assert row["content"] == "reversibly suppressed"
    assert not row["is_stale"]
    assert (
        ext.effective_strength(row["heat_base"], row["extinction_strength"])
        < row["heat_base"]
    )


def test_spontaneous_recovery_returns_association(store):
    mid = _insert(store, "will recover", heat=0.8)
    store.update_memory_extinction(mid, ext.apply_extinction(0.0, 3))
    mem = store.get_memory(mid)
    strong_tag = mem["extinction_strength"]
    out = compute_extinction_action(
        mem, operation="recover", hours_elapsed=ext.RECOVERY_HALF_LIFE_HOURS
    )
    assert out.extinction_strength < strong_tag  # inhibition decayed


def test_reinstate_full_restore(store):
    mid = _insert(store, "will be reinstated", heat=0.75)
    store.update_memory_extinction(mid, ext.apply_extinction(0.0, 3))
    mem = store.get_memory(mid)
    out = compute_extinction_action(mem, operation="reinstate")
    assert out.extinction_strength == pytest.approx(0.0)
    store.update_memory_extinction(mid, out.extinction_strength)
    row = store.get_memory(mid)
    # Original effective strength restored exactly.
    assert ext.effective_strength(
        row["heat_base"], row["extinction_strength"]
    ) == pytest.approx(row["heat_base"])


# ── active_forgetting: reversible alternative to is_stale delete ──────────────
def test_should_extinguish_under_pressure():
    # Sustained accumulated pressure above the accumulation threshold ->
    # extinction warranted (mirrors is_permanent_forgetting's accum test).
    accum = active_forgetting.PERMANENT_ACCUM_THRESHOLD + 0.5
    assert active_forgetting.should_extinguish(
        accum, is_pinned=False, recently_active=False
    )


def test_should_extinguish_exemptions():
    accum = active_forgetting.PERMANENT_ACCUM_THRESHOLD + 0.5
    assert not active_forgetting.should_extinguish(
        accum, is_pinned=True, recently_active=False
    )
    assert not active_forgetting.should_extinguish(
        accum, is_pinned=False, recently_active=True
    )
    assert not active_forgetting.should_extinguish(
        accum, is_pinned=False, recently_active=False, already_stale=True
    )


def test_extinction_distinct_from_deletion():
    # A memory can be a deprecate candidate without being marked is_stale:
    # should_extinguish returns a decision; it never sets is_stale itself.
    accum = active_forgetting.PERMANENT_ACCUM_THRESHOLD + 0.5
    decision = active_forgetting.should_extinguish(accum, False, False)
    assert isinstance(decision, bool)
    # is_permanent_forgetting is the SEPARATE erasure route.
    assert hasattr(active_forgetting, "is_permanent_forgetting")


# ── Ablation guard ───────────────────────────────────────────────────────────
def test_ablation_disables_deprecate(store, monkeypatch):
    monkeypatch.setenv("CORTEX_ABLATE_EXTINCTION", "1")
    mid = _insert(store, "should not deprecate", heat=0.8)
    mem = store.get_memory(mid)
    out = compute_extinction_action(mem, operation="deprecate", trials=3)
    assert out.extinction_strength is None  # store leaves column untouched


def test_ablation_disables_should_extinguish(monkeypatch):
    monkeypatch.setenv("CORTEX_ABLATE_EXTINCTION", "1")
    accum = active_forgetting.PERMANENT_ACCUM_THRESHOLD + 0.5
    assert not active_forgetting.should_extinguish(accum, False, False)


def test_ablation_disables_recover_reinstate(store, monkeypatch):
    monkeypatch.setenv("CORTEX_ABLATE_EXTINCTION", "1")
    mem = {"extinction_strength": 0.8, "heat": 0.5}
    assert (
        compute_extinction_action(
            mem, operation="recover", hours_elapsed=100
        ).extinction_strength
        is None
    )
    assert (
        compute_extinction_action(mem, operation="reinstate").extinction_strength
        is None
    )
