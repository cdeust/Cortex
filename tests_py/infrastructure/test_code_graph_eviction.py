"""Code-graph cache size cap: LRU eviction, never of a graph in use (#711, 3b)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mcp_server.infrastructure import code_graph_cache as cache
from mcp_server.infrastructure import code_graph_eviction as eviction
from mcp_server.infrastructure.code_graph_eviction import GraphEntry


def _graph(base: Path, name: str, size: int, root: Path | None, used: float) -> Path:
    graph_dir = base / name
    (graph_dir / "graph").mkdir(parents=True)
    (graph_dir / "graph" / "data").write_bytes(b"x" * size)
    if root is not None:
        root.mkdir(exist_ok=True)
        cache.write_root_marker(graph_dir, root)
        os.utime(graph_dir / cache.ROOT_MARKER, (used, used))
    return graph_dir


def _root(tmp_path: Path, name: str) -> str:
    return str((tmp_path / name).resolve())


@pytest.mark.parametrize("raw", ["", "  "])
def test_no_cap_when_unset_or_blank(monkeypatch, raw):
    monkeypatch.setenv(eviction.CAP_ENV, raw)
    assert eviction.cache_cap_bytes() is None


@pytest.mark.parametrize(
    ("raw", "expected"), [("5", 5 * 10**9), ("0.5", 5 * 10**8), ("0", 0)]
)
def test_cap_reads_decimal_gigabytes(monkeypatch, raw, expected):
    monkeypatch.setenv(eviction.CAP_ENV, raw)
    assert eviction.cache_cap_bytes() == expected


@pytest.mark.parametrize("raw", ["ten", "-1", "-0", "nan", "inf", "1e-10"])
def test_an_unusable_cap_is_logged_and_sets_none(monkeypatch, caplog, raw):
    monkeypatch.setenv(eviction.CAP_ENV, raw)
    assert eviction.cache_cap_bytes() is None
    assert eviction.CAP_ENV in caplog.text


def test_candidates_are_ordered_oldest_first():
    entries = [
        GraphEntry("new", 40, last_used=300.0, root="/r/new"),
        GraphEntry("old", 40, last_used=100.0, root="/r/old"),
        GraphEntry("mid", 40, last_used=200.0, root="/r/mid"),
    ]
    names = [e.name for e in eviction.eviction_candidates(entries, frozenset())]
    assert names == ["old", "mid", "new"]


def test_candidates_never_include_a_graph_in_use_or_unmarked():
    entries = [
        GraphEntry("live", 100, last_used=1.0, root="/r/live"),
        GraphEntry("legacy", 100, last_used=0.0, root=None),
        GraphEntry("idle", 100, last_used=2.0, root="/r/idle"),
    ]
    candidates = eviction.eviction_candidates(entries, frozenset({"/r/live"}))
    assert [e.name for e in candidates] == ["idle"]


def test_evict_removes_lru_and_keeps_live_and_unmarked(tmp_path):
    base = tmp_path / "code-graphs"
    old = _graph(base, "old", 100, tmp_path / "old", used=1_000.0)
    recent = _graph(base, "recent", 100, tmp_path / "recent", used=2_000.0)
    live = _graph(base, "live", 100, tmp_path / "live", used=500.0)
    legacy = _graph(base, "legacy", 100, None, used=0.0)
    live_roots = frozenset({_root(tmp_path, "live")})

    report = eviction.evict_to_cap(base, cap=300, live_roots=live_roots)

    assert report.removed == ("old", "recent")
    assert not old.exists() and not recent.exists()
    assert live.is_dir() and legacy.is_dir()
    assert report.over_cap is False
    assert report.total_bytes == eviction.directory_size(base)


def test_evict_touches_the_marker_of_a_graph_in_use(tmp_path):
    base = tmp_path / "code-graphs"
    live = _graph(base, "live", 10, tmp_path / "live", used=1_000.0)

    eviction.evict_to_cap(
        base, cap=10**9, live_roots=frozenset({_root(tmp_path, "live")})
    )

    assert (live / cache.ROOT_MARKER).stat().st_mtime > 1_000.0


def test_unknown_live_roots_evict_nothing(tmp_path, caplog):
    base = tmp_path / "code-graphs"
    graph = _graph(base, "idle", 100, tmp_path / "idle", used=1.0)

    report = eviction.evict_to_cap(base, cap=0, live_roots=None)

    assert report.removed == () and report.over_cap is True
    assert graph.is_dir()
    assert "live project roots unknown" in caplog.text


def test_still_over_cap_when_only_live_and_unmarked_remain(tmp_path):
    base = tmp_path / "code-graphs"
    _graph(base, "live", 100, tmp_path / "live", used=1.0)
    _graph(base, "legacy", 100, None, used=0.0)

    report = eviction.evict_to_cap(
        base, cap=50, live_roots=frozenset({_root(tmp_path, "live")})
    )

    assert report.removed == () and report.over_cap is True


def test_a_failed_removal_is_reported_and_not_counted(tmp_path, monkeypatch):
    base = tmp_path / "code-graphs"
    graph = _graph(base, "idle", 100, tmp_path / "idle", used=1.0)

    def _refuse(path):
        raise OSError("busy")

    monkeypatch.setattr(eviction.shutil, "rmtree", _refuse)
    report = eviction.evict_to_cap(base, cap=0, live_roots=frozenset())

    assert report.failed == ("idle",) and report.removed == ()
    assert graph.is_dir() and report.over_cap is True


def test_directory_size_does_not_follow_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big").write_bytes(b"x" * 1000)
    graph = tmp_path / "g"
    graph.mkdir()
    (graph / "small").write_bytes(b"x" * 10)
    try:
        (graph / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")

    assert eviction.directory_size(graph) == 10


def test_a_graph_that_cannot_go_hands_its_turn_to_the_next(tmp_path, monkeypatch):
    # Two idle graphs and a cap that holds one: the oldest is refused, so the
    # newer one goes and the cache fits (Codex P2 on PR #1069).
    base = tmp_path / "code-graphs"
    stuck = _graph(base, "stuck", 100, tmp_path / "stuck", used=1.0)
    newer = _graph(base, "newer", 100, tmp_path / "newer", used=2.0)
    real_rmtree = eviction.shutil.rmtree

    def _refuse_stuck(path):
        if Path(path).name == "stuck":
            raise OSError("busy")
        real_rmtree(path)

    monkeypatch.setattr(eviction.shutil, "rmtree", _refuse_stuck)
    cap = eviction.directory_size(stuck)
    report = eviction.evict_to_cap(base, cap=cap, live_roots=frozenset())

    assert report.failed == ("stuck",) and report.removed == ("newer",)
    assert stuck.is_dir() and not newer.exists()
    assert report.total_bytes == cap and report.over_cap is False
