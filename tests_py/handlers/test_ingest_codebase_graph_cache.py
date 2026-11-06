"""ingest_codebase ties the graph it builds to its root and prunes orphans (#711)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.handlers import ingest_codebase as icb
from mcp_server.handlers import ingest_codebase_graph as graphmod
from mcp_server.infrastructure import code_graph_cache as graph_cache


def test_prune_removes_orphans_beside_the_output_dir(
    tmp_path: Path, monkeypatch
) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(graph_cache, "managed_cache_dir", lambda: cache_dir)
    project = tmp_path / "proj"
    project.mkdir()
    graph_cache.write_root_marker(cache_dir / "proj-1", project)
    gone = tmp_path / "gone"
    gone.mkdir()
    graph_cache.write_root_marker(cache_dir / "gone-2", gone)
    gone.rmdir()

    removed = icb._prune_precedent_graphs(str(cache_dir / "proj-1"))

    assert removed == ["gone-2"]
    assert (cache_dir / "proj-1").is_dir()


def test_prune_expands_a_tilde_output_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    gone = tmp_path / "gone"
    gone.mkdir()
    managed = tmp_path / ".cache" / "cortex" / "code-graphs"
    graph_cache.write_root_marker(managed / "gone-2", gone)
    gone.rmdir()

    assert icb._prune_precedent_graphs("~/.cache/cortex/code-graphs/p-1") == ["gone-2"]


def test_prune_never_touches_siblings_outside_the_managed_cache(
    tmp_path: Path, monkeypatch
) -> None:
    """An explicit output_dir must not let a crafted marker delete a sibling."""
    monkeypatch.setattr(graph_cache, "managed_cache_dir", lambda: tmp_path / "cache")
    victim = tmp_path / "elsewhere" / "victim"
    gone = tmp_path / "gone"
    gone.mkdir()
    graph_cache.write_root_marker(victim, gone)
    gone.rmdir()

    assert icb._prune_precedent_graphs(str(tmp_path / "elsewhere" / "out")) == []
    assert victim.is_dir()


@pytest.mark.asyncio
async def test_analyze_call_records_the_root_of_the_graph_it_builds(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    output_dir = tmp_path / "cache" / "proj-1"
    calls: list[tuple] = []

    async def _fake_upstream(server, tool, args):
        calls.append((server, tool, args))
        output_dir.mkdir(parents=True)
        return {"status": "ok"}

    monkeypatch.setattr(graphmod, "call_upstream", _fake_upstream)
    payload = await graphmod._call_analyze(str(project), str(output_dir), "python")

    assert payload == {"status": "ok"}
    assert calls == [
        (
            "codebase",
            "analyze_codebase",
            {
                "path": str(project.resolve()),
                "output_dir": str(output_dir.resolve()),
                "language": "python",
            },
        )
    ]
    assert graph_cache.read_root_marker(output_dir) == str(project.resolve())
