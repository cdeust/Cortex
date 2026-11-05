"""Code-graph cache root markers and orphan pruning (issue #711)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mcp_server.infrastructure import code_graph_cache as cache


def _graph(cache_dir: Path, name: str, root: Path | None) -> Path:
    graph_dir = cache_dir / name
    (graph_dir / "graph").mkdir(parents=True)
    (graph_dir / "graph" / "data").write_bytes(b"x")
    if root is not None:
        cache.write_root_marker(graph_dir, root)
    return graph_dir


def test_marker_records_the_resolved_root(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    graph_dir = tmp_path / "cache" / "proj-1234abcd"
    cache.write_root_marker(graph_dir, root / ".." / "proj")
    data = json.loads((graph_dir / cache.ROOT_MARKER).read_text(encoding="utf-8"))
    assert data == {"project_root": str(root.resolve())}
    assert cache.read_root_marker(graph_dir) == str(root.resolve())


def test_graph_of_a_deleted_root_is_pruned(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    cache_dir = tmp_path / "cache"
    graph_dir = _graph(cache_dir, "wt-0000aaaa", worktree)
    worktree.rmdir()

    report = cache.prune_orphan_graphs(cache_dir)

    assert report.removed == ("wt-0000aaaa",)
    assert not graph_dir.exists()


def test_graph_of_a_live_root_is_kept(tmp_path: Path) -> None:
    root = tmp_path / "live"
    root.mkdir()
    cache_dir = tmp_path / "cache"
    graph_dir = _graph(cache_dir, "live-1111bbbb", root)

    report = cache.prune_orphan_graphs(cache_dir)

    assert report.removed == ()
    assert graph_dir.is_dir()


def test_directory_without_marker_is_reported_not_deleted(
    tmp_path: Path, caplog
) -> None:
    cache_dir = tmp_path / "cache"
    legacy = _graph(cache_dir, "legacy-2222cccc", None)

    with caplog.at_level(logging.WARNING, logger=cache.__name__):
        report = cache.prune_orphan_graphs(cache_dir)

    assert report.unattributed == ("legacy-2222cccc",)
    assert report.removed == ()
    assert legacy.is_dir()
    assert "legacy-2222cccc" in caplog.text


def test_unreadable_marker_counts_as_unattributed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    graph_dir = _graph(cache_dir, "bad-3333dddd", None)
    (graph_dir / cache.ROOT_MARKER).write_text("{not json", encoding="utf-8")

    report = cache.prune_orphan_graphs(cache_dir)

    assert report.unattributed == ("bad-3333dddd",)
    assert graph_dir.is_dir()


def test_prefix_sharing_project_is_not_touched(tmp_path: Path) -> None:
    """The former name-prefix prune removed ``cortex-viz-*`` when ``cortex`` ran."""
    cortex = tmp_path / "cortex"
    viz = tmp_path / "cortex-viz"
    cortex.mkdir()
    viz.mkdir()
    cache_dir = tmp_path / "cache"
    _graph(cache_dir, "cortex-4444eeee", cortex)
    viz_graph = _graph(cache_dir, "cortex-viz-5555ffff", viz)

    report = cache.prune_orphan_graphs(cache_dir)

    assert report.removed == ()
    assert viz_graph.is_dir()


def test_missing_cache_dir_is_empty_report(tmp_path: Path) -> None:
    report = cache.prune_orphan_graphs(tmp_path / "absent")
    assert report == cache.PruneReport((), (), ())


def test_marker_altered_by_redaction_is_removed(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    """A redacted root would name a missing path and get the graph pruned."""
    root = tmp_path / "proj"
    root.mkdir()
    graph_dir = tmp_path / "cache" / "proj-6666aaaa"
    graph_dir.mkdir(parents=True)
    real_write = cache.gated_files.write_json

    def _redacting_write(path, data, **kwargs):
        return real_write(path, {"project_root": "REDACTED"}, **kwargs)

    monkeypatch.setattr(cache.gated_files, "write_json", _redacting_write)
    with caplog.at_level(logging.WARNING, logger=cache.__name__):
        cache.write_root_marker(graph_dir, root)

    assert caplog.messages == [
        f"root marker for {graph_dir} was altered by redaction; removed"
    ]

    assert not (graph_dir / cache.ROOT_MARKER).exists()
    assert cache.prune_orphan_graphs(graph_dir.parent).unattributed == (
        "proj-6666aaaa",
    )


def test_tilde_paths_expand_to_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "proj").mkdir()
    cache.write_root_marker("~/cache/proj-7777aaaa", "~/proj")
    graph_dir = tmp_path / "cache" / "proj-7777aaaa"
    assert cache.read_root_marker(graph_dir) == str((tmp_path / "proj").resolve())
    (tmp_path / "proj").rmdir()
    assert cache.prune_orphan_graphs("~/cache").removed == ("proj-7777aaaa",)


def test_prune_logs_removed_and_unattributed(tmp_path: Path, caplog) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    cache_dir = tmp_path / "cache"
    _graph(cache_dir, "gone-8888aaaa", gone)
    _graph(cache_dir, "legacy-8888bbbb", None)
    gone.rmdir()

    with caplog.at_level(logging.INFO, logger=cache.__name__):
        cache.prune_orphan_graphs(cache_dir)

    assert caplog.messages == [
        "pruned 1 orphan code graph(s): ['gone-8888aaaa']",
        f"1 code graph(s) under {cache_dir} carry no cortex-root.json and cannot "
        "be tied to a project root; kept, remove by hand if unused: "
        "['legacy-8888bbbb']",
    ]


def test_failed_removal_is_reported(tmp_path: Path, monkeypatch, caplog) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    cache_dir = tmp_path / "cache"
    graph_dir = _graph(cache_dir, "gone-9999aaaa", gone)
    gone.rmdir()

    def _refuse(path):
        raise OSError("busy")

    monkeypatch.setattr(cache.shutil, "rmtree", _refuse)
    with caplog.at_level(logging.WARNING, logger=cache.__name__):
        report = cache.prune_orphan_graphs(cache_dir)

    assert report == cache.PruneReport((), (), ("gone-9999aaaa",))
    assert caplog.messages == [f"could not prune orphan graph {graph_dir}: busy"]


def test_plain_file_in_cache_is_skipped(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    cache_dir = tmp_path / "cache"
    _graph(cache_dir, "b-gone", gone)
    (cache_dir / "a-stray.txt").write_text("x", encoding="utf-8")
    gone.rmdir()
    assert cache.prune_orphan_graphs(cache_dir) == cache.PruneReport(
        ("b-gone",), (), ()
    )


def test_marker_without_a_root_string_is_unattributed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    for name, payload in (
        ("list-1", "[]"),
        ("empty-2", '{"project_root": ""}'),
        ("number-3", '{"project_root": 3}'),
        ("missing-4", '{"other": "/x"}'),
    ):
        graph_dir = _graph(cache_dir, name, None)
        (graph_dir / cache.ROOT_MARKER).write_text(payload, encoding="utf-8")
    report = cache.prune_orphan_graphs(cache_dir)
    assert report.unattributed == ("empty-2", "list-1", "missing-4", "number-3")


def test_record_root_writes_the_marker_when_the_dir_exists(tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    cache.record_root(tmp_path / "out", tmp_path)
    assert cache.read_root_marker(tmp_path / "out") == str(tmp_path.resolve())


def test_record_root_expands_a_tilde_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "out").mkdir()
    cache.record_root("~/out", tmp_path)
    assert cache.read_root_marker(tmp_path / "out") == str(tmp_path.resolve())


def test_record_root_creates_nothing_for_an_absent_dir(tmp_path: Path) -> None:
    cache.record_root(tmp_path / "never-built", tmp_path)
    assert not (tmp_path / "never-built").exists()


def test_record_root_logs_a_failed_write(tmp_path: Path, monkeypatch, caplog) -> None:
    (tmp_path / "out").mkdir()

    def _refuse(graph_dir, project_root):
        raise OSError("read-only")

    monkeypatch.setattr(cache, "write_root_marker", _refuse)
    with caplog.at_level(logging.WARNING, logger=cache.__name__):
        cache.record_root(tmp_path / "out", tmp_path)
    assert caplog.messages == [
        f"could not write root marker in {tmp_path / 'out'}: read-only"
    ]
