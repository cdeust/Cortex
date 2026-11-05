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


def test_default_cache_dir_is_under_the_user_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    assert cache.default_cache_dir() == tmp_path / ".cache" / "cortex" / "code-graphs"


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


def test_marker_altered_by_redaction_is_removed(tmp_path: Path, monkeypatch) -> None:
    """A redacted root would name a missing path and get the graph pruned."""
    root = tmp_path / "proj"
    root.mkdir()
    graph_dir = tmp_path / "cache" / "proj-6666aaaa"
    graph_dir.mkdir(parents=True)
    real_write = cache.gated_files.write_json

    def _redacting_write(path, data, **kwargs):
        return real_write(path, {"project_root": "REDACTED"}, **kwargs)

    monkeypatch.setattr(cache.gated_files, "write_json", _redacting_write)
    cache.write_root_marker(graph_dir, root)

    assert not (graph_dir / cache.ROOT_MARKER).exists()
    assert cache.prune_orphan_graphs(graph_dir.parent).unattributed == (
        "proj-6666aaaa",
    )
