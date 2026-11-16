"""What the code-graph eviction reports and logs, exactly (#711, slice 3b).

The worker's log is the only trace a user has of an eviction, so each message,
each total and each over-cap verdict is pinned here."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from mcp_server.infrastructure import code_graph_cache as cache
from mcp_server.infrastructure import code_graph_eviction as eviction
from mcp_server.infrastructure.code_graph_eviction import EvictionReport


def _graph(base: Path, name: str, size: int, root: Path | None, used: float) -> Path:
    graph_dir = base / name
    (graph_dir / "graph").mkdir(parents=True)
    (graph_dir / "graph" / "data").write_bytes(b"x" * size)
    if root is not None:
        root.mkdir(exist_ok=True)
        cache.write_root_marker(graph_dir, root)
        os.utime(graph_dir / cache.ROOT_MARKER, (used, used))
    return graph_dir


def _messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == eviction.__name__]


def test_an_unset_cap_is_none_and_logs_nothing(monkeypatch, caplog):
    monkeypatch.delenv(eviction.CAP_ENV, raising=False)
    with caplog.at_level(logging.INFO):
        assert eviction.cache_cap_bytes() is None
    assert _messages(caplog) == []


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("ten", "='ten' is not a number; no code-graph eviction"),
        ("-1", "='-1' is negative; no eviction"),
        ("inf", "='inf' is not a finite size; no eviction"),
        ("1e300", "='1e300' is not a finite size; no eviction"),
        ("-0", "='-0' is negative; no eviction"),
        ("1e-10", "='1e-10' is below one byte; no eviction"),
        ("1e-400", "='1e-400' is below one byte; no eviction"),
        ("1e-1000100", "='1e-1000100' is below one byte; no eviction"),
        (
            "1e-99999999999999999999",
            "='1e-99999999999999999999' has an exponent out of range; no eviction",
        ),
    ],
)
def test_an_unusable_cap_logs_the_value(monkeypatch, caplog, raw, message):
    monkeypatch.setenv(eviction.CAP_ENV, raw)
    assert eviction.cache_cap_bytes() is None
    assert _messages(caplog) == [eviction.CAP_ENV + message]


def test_scan_reads_the_marker_mtime_and_skips_files_and_links(tmp_path):
    base = tmp_path / "code-graphs"
    _graph(base, "marked", 5, tmp_path / "root", used=1_234.0)
    _graph(base, "legacy", 7, None, used=0.0)
    (base / "stray-file").write_bytes(b"x")
    try:
        (base / "linked").symlink_to(base / "marked", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")

    entries = {e.name: e for e in eviction.scan_entries(base)}

    assert sorted(entries) == ["legacy", "marked"]
    assert entries["marked"].last_used == 1_234.0
    assert entries["legacy"].last_used == 0.0 and entries["legacy"].root is None
    assert entries["legacy"].size == 7


def test_a_file_that_vanishes_is_skipped_not_the_rest(tmp_path, monkeypatch):
    for name in ("a", "b", "c"):
        (tmp_path / name).write_bytes(b"x" * 10)
    real_lstat = os.lstat
    calls = []

    def _first_fails(path):
        calls.append(path)
        if len(calls) == 1:
            raise FileNotFoundError(path)
        return real_lstat(path)

    monkeypatch.setattr(eviction.os, "lstat", _first_fails)
    assert eviction.directory_size(tmp_path) == 20


def test_unknown_live_roots_report_the_total(tmp_path, caplog):
    base = tmp_path / "code-graphs"
    _graph(base, "idle", 100, tmp_path / "idle", used=1.0)
    total = eviction.directory_size(base)

    assert eviction.evict_to_cap(base, cap=total - 1, live_roots=None) == (
        EvictionReport((), (), total, True)
    )
    assert eviction.evict_to_cap(base, cap=total, live_roots=None) == (
        EvictionReport((), (), total, False)
    )
    assert _messages(caplog)[0] == "live project roots unknown; no code-graph eviction"


def test_a_total_equal_to_the_cap_is_not_over_it(tmp_path):
    base = tmp_path / "code-graphs"
    _graph(base, "old", 100, tmp_path / "old", used=1.0)
    keep = _graph(base, "new", 100, tmp_path / "new", used=2.0)
    kept = eviction.directory_size(keep)

    report = eviction.evict_to_cap(base, cap=kept, live_roots=frozenset())

    assert report == EvictionReport(("old",), (), kept, False)


def test_one_failed_removal_does_not_stop_the_next(tmp_path, monkeypatch, caplog):
    base = tmp_path / "code-graphs"
    stuck = _graph(base, "stuck", 100, tmp_path / "stuck", used=1.0)
    _graph(base, "next", 100, tmp_path / "next", used=2.0)
    real_rmtree = eviction.shutil.rmtree

    def _refuse_stuck(path):
        if Path(path).name == "stuck":
            raise OSError("busy")
        real_rmtree(path)

    monkeypatch.setattr(eviction.shutil, "rmtree", _refuse_stuck)
    with caplog.at_level(logging.INFO):
        report = eviction.evict_to_cap(base, cap=0, live_roots=frozenset())

    assert report.removed == ("next",) and report.failed == ("stuck",)
    assert _messages(caplog) == [
        f"could not evict code graph {stuck}: busy",
        "evicted 1 code graph(s) over the cap: ['next']",
    ]


def test_the_evicted_names_are_logged(tmp_path, caplog):
    base = tmp_path / "code-graphs"
    _graph(base, "a", 10, tmp_path / "a", used=1.0)
    _graph(base, "b", 10, tmp_path / "b", used=2.0)
    with caplog.at_level(logging.INFO):
        eviction.evict_to_cap(base, cap=0, live_roots=frozenset())
    assert _messages(caplog) == ["evicted 2 code graph(s) over the cap: ['a', 'b']"]


def test_a_marker_that_cannot_be_touched_is_logged(tmp_path, monkeypatch, caplog):
    base = tmp_path / "code-graphs"
    _graph(base, "live", 10, tmp_path / "live", used=1.0)

    def _deny(path, times=None):
        raise PermissionError("denied")

    monkeypatch.setattr(eviction.os, "utime", _deny)
    live = frozenset({str((tmp_path / "live").resolve())})
    report = eviction.evict_to_cap(base, cap=0, live_roots=live)

    assert report.removed == ()
    assert _messages(caplog) == ["could not touch marker of live: denied"]
