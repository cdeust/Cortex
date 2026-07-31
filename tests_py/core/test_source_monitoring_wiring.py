"""Integration test for C1 source-monitoring wiring.

Verifies that a written memory's epistemic attribution is classified from its
content and persisted on the memories.source_attribution column, using the real
sqlite store (no Postgres required).
"""

from __future__ import annotations

import os
import tempfile

import pytest

from mcp_server.core import source_monitoring as sm
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


def _insert(store, content, source="user"):
    rec = {
        "content": content,
        "tags": [],
        "source": source,
        "source_attribution": sm.classify_source(
            content, source_field=source
        ).attribution,
    }
    return store.insert_memory(rec)


def test_perceived_memory_persists_attribution(store):
    mid = _insert(store, "The value column is defined in pg_schema.py line 43")
    row = store.get_memory(mid)
    assert row["source_attribution"] == "perceived"


def test_inferred_memory_persists_attribution(store):
    mid = _insert(store, "I think the decay is probably too aggressive, it seems wrong")
    row = store.get_memory(mid)
    assert row["source_attribution"] == "inferred"


def test_told_memory_persists_attribution(store):
    mid = _insert(store, "You asked me to keep the reranker alpha at 0.70")
    row = store.get_memory(mid)
    assert row["source_attribution"] == "told"


def test_default_attribution_when_absent(store):
    # A record that predates the classifier (no source_attribution key) gets the
    # column default 'unknown', not a crash.
    mid = store.insert_memory(
        {"content": "plain content", "tags": [], "source": "user"}
    )
    row = store.get_memory(mid)
    assert row["source_attribution"] == "unknown"


def test_external_pathway_marks_perceived(store):
    # A tool-captured memory is externally sourced by construction.
    mid = _insert(store, "some captured content", source="post_tool_capture")
    row = store.get_memory(mid)
    assert row["source_attribution"] == "perceived"
