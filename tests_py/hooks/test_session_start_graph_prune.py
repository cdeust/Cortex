"""SessionStart prunes orphaned code graphs even when it ingests nothing (#711).

Before slice 2, the only pruning ran after ``ingest_codebase`` had built a
graph, so a session with a fresh graph or no pipeline left every deleted
worktree's graph on disk. The hook now reads the markers and, when an orphan
exists, starts the detached ``code_graph_prune_background`` worker."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.hooks import code_graph_prune_background as worker
from mcp_server.hooks import session_start_background as background
from mcp_server.infrastructure import code_graph_cache as cache
from mcp_server.infrastructure import code_graph_eviction as eviction
from mcp_server.shared import detached_spawn
from tests_py.hooks._spawn_logged_fake import fake_spawn

WORKER = "mcp_server.hooks.code_graph_prune_background"


@pytest.fixture
def managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty managed cache under a temporary home."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CORTEX_CLAUDE_DIR", raising=False)
    managed_dir = cache.managed_cache_dir()
    managed_dir.mkdir(parents=True)
    return managed_dir


def _graph(cache_dir: Path, name: str, root: Path | None) -> Path:
    graph_dir = cache_dir / name
    (graph_dir / "graph").mkdir(parents=True)
    (graph_dir / "graph" / "data").write_bytes(b"x")
    if root is not None:
        root.mkdir()
        cache.write_root_marker(graph_dir, root)
    return graph_dir


def _orphan(cache_dir: Path, tmp_path: Path, name: str) -> Path:
    root = tmp_path / f"root-{name}"
    graph_dir = _graph(cache_dir, name, root)
    root.rmdir()
    return graph_dir


def test_orphan_scan_names_only_orphans_and_deletes_nothing(managed, tmp_path):
    orphan = _orphan(managed, tmp_path, "gone-0000aaaa")
    _graph(managed, "live-1111bbbb", tmp_path / "live")
    _graph(managed, "legacy-2222cccc", None)

    assert cache.orphan_graphs(managed) == ("gone-0000aaaa",)
    assert orphan.is_dir()


def test_an_orphan_starts_the_pruning_worker(managed, tmp_path, monkeypatch, capsys):
    _orphan(managed, tmp_path, "gone-0000aaaa")
    calls = fake_spawn(monkeypatch, background)

    background._maybe_background_prune_graphs()

    assert len(calls) == 1
    assert WORKER in calls[0]["cmd"]
    assert calls[0]["log_path"].name == "code_graph_prune.log"
    assert calls[0]["kwargs"] == detached_spawn.options()
    assert (
        f"code-graph prune spawned for 1 orphan(s) → {calls[0]['log_path']}"
        in capsys.readouterr().err
    )


def test_no_orphan_starts_nothing(managed, tmp_path, monkeypatch):
    _graph(managed, "live-1111bbbb", tmp_path / "live")
    _graph(managed, "legacy-2222cccc", None)
    calls = fake_spawn(monkeypatch, background)

    background._maybe_background_prune_graphs()

    assert calls == []


def test_a_failed_spawn_is_logged_not_raised(managed, tmp_path, monkeypatch, capsys):
    _orphan(managed, tmp_path, "gone-0000aaaa")

    def _refuse(cmd, log_path, **kwargs):
        raise OSError("no fork")

    fake_spawn(monkeypatch, background, popen=_refuse)

    background._maybe_background_prune_graphs()

    assert "code-graph prune skipped: no fork" in capsys.readouterr().err


def test_the_worker_prunes_the_managed_cache(managed, tmp_path, capsys):
    orphan = _orphan(managed, tmp_path, "gone-0000aaaa")
    live = _graph(managed, "live-1111bbbb", tmp_path / "live")

    legacy = _graph(managed, "legacy-2222cccc", None)

    assert worker.main() == 0

    assert not orphan.exists()
    assert live.is_dir()
    assert legacy.is_dir()
    assert capsys.readouterr().out.splitlines() == [
        "[bg-graph-prune] removed: ['gone-0000aaaa']",
        "[bg-graph-prune] unattributed (kept): ['legacy-2222cccc']",
        "[bg-graph-prune] failed: []",
    ]


def test_a_failed_removal_exits_1(managed, tmp_path, monkeypatch, capsys):
    orphan = _orphan(managed, tmp_path, "gone-0000aaaa")

    def _refuse(path):
        raise OSError("busy")

    monkeypatch.setattr(cache.shutil, "rmtree", _refuse)

    assert worker.main() == 1

    assert orphan.is_dir()
    assert "[bg-graph-prune] failed: ['gone-0000aaaa']" in capsys.readouterr().out


def test_a_cap_starts_the_worker_without_orphans(
    managed, tmp_path, monkeypatch, capsys
):
    _graph(managed, "live-1111bbbb", tmp_path / "live")
    monkeypatch.setenv("CORTEX_CODE_GRAPH_CACHE_MAX_GB", "5")
    calls = fake_spawn(monkeypatch, background)

    background._maybe_background_prune_graphs()

    assert len(calls) == 1
    assert (
        f"code-graph prune spawned for the cache cap → {calls[0]['log_path']}"
        in capsys.readouterr().err
    )


def test_an_orphan_and_a_cap_name_both_reasons(managed, tmp_path, monkeypatch, capsys):
    _orphan(managed, tmp_path, "gone-0000aaaa")
    monkeypatch.setenv("CORTEX_CODE_GRAPH_CACHE_MAX_GB", "5")
    calls = fake_spawn(monkeypatch, background)

    background._maybe_background_prune_graphs()

    assert (
        f"code-graph prune spawned for 1 orphan(s) and the cache cap → "
        f"{calls[0]['log_path']}" in capsys.readouterr().err
    )


def test_the_worker_evicts_over_the_cap_but_not_a_live_graph(
    managed, tmp_path, monkeypatch, capsys
):
    idle = _graph(managed, "idle-3333dddd", tmp_path / "idle")
    live = _graph(managed, "live-1111bbbb", tmp_path / "live")
    live_roots = frozenset({str((tmp_path / "live").resolve())})
    monkeypatch.setattr(worker, "live_project_roots", lambda: live_roots)
    monkeypatch.setenv("CORTEX_CODE_GRAPH_CACHE_MAX_GB", "0")

    assert worker.main() == 0

    assert not idle.exists()
    assert live.is_dir()
    total = eviction.directory_size(managed)
    assert capsys.readouterr().out.splitlines()[3:] == [
        f"[bg-graph-evict] cap: 0 bytes, total after: {total}",
        "[bg-graph-evict] removed: ['idle-3333dddd']",
        "[bg-graph-evict] failed: []",
        "[bg-graph-evict] still over the cap: the rest is in use or unmarked",
    ]


def test_no_cap_runs_no_eviction(managed, tmp_path, monkeypatch, capsys):
    idle = _graph(managed, "idle-3333dddd", tmp_path / "idle")
    monkeypatch.delenv("CORTEX_CODE_GRAPH_CACHE_MAX_GB", raising=False)

    assert worker.main() == 0

    assert idle.is_dir()
    assert "bg-graph-evict" not in capsys.readouterr().out


def test_a_failed_prune_still_runs_the_eviction(managed, tmp_path, monkeypatch, capsys):
    _orphan(managed, tmp_path, "gone-0000aaaa")
    idle = _graph(managed, "idle-3333dddd", tmp_path / "idle")
    real_rmtree = cache.shutil.rmtree

    def _refuse_the_orphan(path):
        if Path(path).name == "gone-0000aaaa":
            raise OSError("busy")
        real_rmtree(path)

    monkeypatch.setattr(cache.shutil, "rmtree", _refuse_the_orphan)
    monkeypatch.setattr(worker, "live_project_roots", lambda: frozenset())
    monkeypatch.setenv("CORTEX_CODE_GRAPH_CACHE_MAX_GB", "0")

    assert worker.main() == 1

    assert not idle.exists()
    out = capsys.readouterr().out
    assert "[bg-graph-evict] removed: ['idle-3333dddd']" in out
    # rmtree is one global: the eviction retries the orphan and fails on it too.
    assert "[bg-graph-evict] failed: ['gone-0000aaaa']" in out
