"""Integration test for E1 habituation wiring into the write gate.

Verifies, against the real sqlite store (no Postgres required):
  - the stimulus_signature column persists on written memories;
  - signature_repeat_stats counts prior identical presentations;
  - write_gate.apply_habituation damps a repeated low-salience input's novelty
    (Rankin 2009 response decrement) while leaving a first-seen input unchanged;
  - a salient event dishabituates / sensitizes;
  - CORTEX_ABLATE_HABITUATION=1 fully disables the mechanism (identity).
"""

from __future__ import annotations

import os
import tempfile

import pytest

from mcp_server.core import habituation, write_gate
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


def _insert(store, content):
    sig = habituation.stimulus_signature(content)
    return store.insert_memory(
        {"content": content, "tags": [], "stimulus_signature": sig}
    )


# ── Persistence + read side ──────────────────────────────────────────────────
def test_signature_persists(store):
    content = "the build passed on ci"
    mid = _insert(store, content)
    row = store.get_memory(mid)
    assert row["stimulus_signature"] == habituation.stimulus_signature(content)


def test_repeat_stats_counts_identical(store):
    content = "duplicate log entry"
    sig = habituation.stimulus_signature(content)
    for _ in range(3):
        _insert(store, content)
    count, hours = store.signature_repeat_stats(sig)
    assert count == 3
    assert hours is not None and hours >= 0.0


def test_repeat_stats_unseen(store):
    assert store.signature_repeat_stats("never written") == (0, None)


def test_repeat_stats_empty_signature(store):
    assert store.signature_repeat_stats("") == (0, None)


# ── Gate integration ─────────────────────────────────────────────────────────
def test_first_seen_novelty_unchanged(store):
    nov, info = write_gate.apply_habituation(0.8, "a fresh thought", 0.3, store)
    assert nov == pytest.approx(0.8)
    assert info is not None and info["suppressed"] is False
    assert info["combined_gain"] == pytest.approx(1.0)


def test_repeated_low_salience_suppressed(store):
    content = "the same repeated line"
    for _ in range(4):
        _insert(store, content)
    nov, info = write_gate.apply_habituation(0.8, content, 0.3, store)
    assert nov < 0.8
    assert info["suppressed"] is True
    assert info["response_gain"] < 1.0


def test_salient_event_dishabituates(store):
    content = "recurring but now important"
    for _ in range(4):
        _insert(store, content)
    low, _ = write_gate.apply_habituation(0.6, content, 0.3, store)
    high, info = write_gate.apply_habituation(0.6, content, 0.95, store)
    assert high > low  # salience raises the response back up
    assert info["sensitization"] > 1.0


def test_ablation_disables_mechanism(store):
    content = "should be habituated"
    for _ in range(5):
        _insert(store, content)
    os.environ["CORTEX_ABLATE_HABITUATION"] = "1"
    try:
        nov, info = write_gate.apply_habituation(0.8, content, 0.3, store)
    finally:
        del os.environ["CORTEX_ABLATE_HABITUATION"]
    assert nov == 0.8
    assert info is None


def test_non_fatal_on_bad_store():
    class Broken:
        def signature_repeat_stats(self, sig):
            raise RuntimeError("boom")

    nov, info = write_gate.apply_habituation(0.7, "content", 0.3, Broken())
    assert nov == 0.7
    assert info is None
