"""``claim_reanalysis_slot``: one background re-analysis per project per window.

The claim is one atomic create (``O_CREAT | O_EXCL``) of a stamp keyed by the
project and the TTL window, so two SessionStarts racing for the same window
cannot both win (review of #751: stat-then-touch let both through).

source: ADR-0585
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from mcp_server.infrastructure import pipeline_graph_ttl as ttl

_HOUR = 3600.0  # source: seconds per hour (graph_ttl_hours is in hours)


@pytest.fixture()
def methodology(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "24")
    return tmp_path / "claude" / "methodology"


def _stamps(methodology: Path) -> list[str]:
    return sorted(p.name for p in methodology.glob("pipeline_reanalyze.*.stamp"))


def test_first_claim_wins_and_a_second_in_the_window_loses(methodology, tmp_path):
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is False
    assert len(_stamps(methodology)) == 1


def test_projects_claim_independently(methodology, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert ttl.claim_reanalysis_slot(str(tmp_path / "a")) is True
    assert ttl.claim_reanalysis_slot(str(tmp_path / "b")) is True


def test_the_next_window_reopens_the_slot_and_prunes_the_old_stamp(
    methodology, tmp_path, monkeypatch
):
    now = 1_000 * 24 * _HOUR
    monkeypatch.setattr(ttl.time, "time", lambda: now)
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True
    first = _stamps(methodology)
    monkeypatch.setattr(ttl.time, "time", lambda: now + 24 * _HOUR)
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True
    second = _stamps(methodology)
    assert len(second) == 1 and second != first, (
        "one stamp per project, not one per day"
    )


def test_a_zero_ttl_bounds_nothing(methodology, tmp_path, monkeypatch):
    """TTL 0 makes every graph stale (graph_is_stale) and every claim win."""
    monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "0")
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True


def test_two_sessions_racing_for_one_window_start_one_ingest(
    methodology, tmp_path, monkeypatch
):
    """Both racers pass every check before either creates its stamp: a
    barrier holds them in the methodology-directory ``mkdir`` that precedes
    the create. Only an atomic create lets exactly one through."""
    barrier = threading.Barrier(2, timeout=5)
    real_mkdir = Path.mkdir

    def mkdir_in_lockstep(self, *args, **kwargs):
        if self == methodology:
            barrier.wait()
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_in_lockstep)
    results: list[bool] = []

    def claim() -> None:
        results.append(ttl.claim_reanalysis_slot(str(tmp_path)))

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(results) == [False, True]


def test_the_claim_is_an_exclusive_create(methodology, tmp_path, monkeypatch):
    flags_seen: list[int] = []
    real_open = os.open

    def recording_open(path, flags, *args):
        flags_seen.append(flags)
        return real_open(path, flags, *args)

    monkeypatch.setattr(ttl.os, "open", recording_open)
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True
    assert flags_seen and all(f & os.O_CREAT and f & os.O_EXCL for f in flags_seen)


def test_a_delayed_claimer_never_prunes_a_later_window(
    methodology, tmp_path, monkeypatch
):
    """A claimer that computed window N after another session already claimed
    N+1 (the boundary passed between them) must leave N+1's stamp, or a third
    session would win N+1 again. Only strictly older windows are pruned."""
    now = 1_000 * 24 * _HOUR
    monkeypatch.setattr(ttl.time, "time", lambda: now + 24 * _HOUR)
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True
    monkeypatch.setattr(ttl.time, "time", lambda: now - 24 * _HOUR)
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True
    monkeypatch.setattr(ttl.time, "time", lambda: now)
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is True
    windows = sorted(int(name.split(".")[2]) for name in _stamps(methodology))
    assert windows == [1_000, 1_001]
    monkeypatch.setattr(ttl.time, "time", lambda: now + 24 * _HOUR)
    assert ttl.claim_reanalysis_slot(str(tmp_path)) is False
