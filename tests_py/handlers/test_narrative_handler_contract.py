"""The narrative handler's contract: which memories it reads and what it returns.

The handler picks one read (a directory, else an explicit domain, else the hot
memories), then returns either a brief summary with its memory count or the full
narrative labelled with the directory or the domain. The core renderers are
replaced by recorders, so each test reads exactly what the handler passed and
returned.

source: mcp_server/handlers/narrative.py; issue #721"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.handlers import narrative
from mcp_server.shared import domain_mapping as dm

_MEMORIES = [{"id": 1}, {"id": 2}, {"id": 3}]


class _RecordingStore:
    """Records every read with its arguments and returns three memories."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_memories_for_directory(self, *args, **kwargs):
        self.calls.append(("directory", args, kwargs))
        return list(_MEMORIES)

    def get_memories_for_domain(self, *args, **kwargs):
        self.calls.append(("domain", args, kwargs))
        return list(_MEMORIES)

    def get_hot_memories(self, *args, **kwargs):
        self.calls.append(("hot", args, kwargs))
        return list(_MEMORIES)


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Run the public handler; return (result, store reads, renderer calls)."""
    monkeypatch.setattr(dm, "_candidate_dev_roots", lambda: [tmp_path])
    dm._build_registry.cache_clear()
    store = _RecordingStore()
    rendered: list[tuple] = []

    def brief(memories):
        rendered.append(("brief", memories))
        return "brief summary"

    def full(memories, **kwargs):
        rendered.append(("full", memories, kwargs))
        return {"narrative": "story"}

    monkeypatch.setattr(narrative, "_get_store", lambda: store)
    monkeypatch.setattr(narrative, "generate_brief_summary", brief)
    monkeypatch.setattr(narrative, "generate_narrative", full)

    def call(args):
        result = asyncio.run(narrative.handler(args))
        return result, store.calls, rendered

    yield call
    dm._build_registry.cache_clear()


def test_no_arguments_reads_hot_memories(run):
    _, calls, _ = run(None)
    assert calls == [("hot", (), {"min_heat": 0.1, "limit": 200})]


def test_empty_arguments_read_hot_memories(run):
    _, calls, _ = run({})
    assert calls == [("hot", (), {"min_heat": 0.1, "limit": 200})]


def test_directory_reads_every_memory_of_the_directory(run):
    _, calls, _ = run({"directory": "/work/repo"})
    assert calls == [("directory", ("/work/repo",), {"min_heat": 0.0})]


def test_directory_wins_over_domain(run):
    _, calls, _ = run({"directory": "/work/repo", "domain": "cortex"})
    assert [c[0] for c in calls] == ["directory"]


def test_domain_reads_up_to_200_memories_at_any_heat(run):
    _, calls, _ = run({"domain": "cortex"})
    assert calls == [("domain", ("cortex",), {"min_heat": 0.0, "limit": 200})]


def test_default_is_the_full_narrative_labelled_by_directory(run):
    result, _, rendered = run({"directory": "/work/repo"})
    assert result == {"narrative": "story"}
    assert rendered == [("full", _MEMORIES, {"directory": "/work/repo"})]


def test_full_narrative_is_labelled_by_the_resolved_domain(run):
    _, _, rendered = run({"domain": " Cortex"})
    assert rendered == [("full", _MEMORIES, {"directory": "cortex"})]


def test_full_narrative_without_scope_has_an_empty_label(run):
    _, _, rendered = run({"brief": False})
    assert rendered == [("full", _MEMORIES, {"directory": ""})]


def test_brief_returns_the_summary_and_the_memory_count(run):
    result, _, rendered = run({"domain": "cortex", "brief": True})
    assert result == {"summary": "brief summary", "memory_count": 3}
    assert rendered == [("brief", _MEMORIES)]
