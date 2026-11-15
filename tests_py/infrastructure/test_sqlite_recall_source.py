"""The SQLite recall projection carries the writer's ``source`` (ADR-1140).

The low-signal filter of default recall keys on ``source``
(``shared/capture_source.py``). PostgreSQL's ``recall_memories`` already
returns it; without it in the SQLite projection every capture would pass
the filter on the default store. This test reads a real in-memory store.
"""

from __future__ import annotations

from mcp_server.handlers.recall_helpers import filter_low_signal
from mcp_server.infrastructure import sqlite_store_recall
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_DOMAIN = "sqlite-recall-source-test"


def test_recall_rows_carry_source_and_the_filter_reads_it() -> None:
    store = SqliteMemoryStore(db_path=":memory:", embedding_dim=384)
    try:
        for content, source, tags in (
            ("deploy pipeline capture output", "post_tool_capture", []),
            ("deploy pipeline user note", "user", ["auto-captured", "imported"]),
        ):
            store.insert_memory(
                {
                    "content": content,
                    "source": source,
                    "tags": tags,
                    "domain": _DOMAIN,
                    "embedding": None,
                }
            )
        rows = store.recall_memories(
            query_text="deploy pipeline",
            query_embedding=None,
            intent="general",
            domain=_DOMAIN,
            min_heat=0.0,
            max_results=10,
        )
    finally:
        store.close()
    assert sorted(r["source"] for r in rows) == ["post_tool_capture", "user"]
    kept, dropped = filter_low_signal(rows)
    assert dropped == 1
    assert [r["content"] for r in kept] == ["deploy pipeline user note"]


def test_result_projects_every_field_of_the_row() -> None:
    """Pin the whole store-neutral shape ``_result`` builds from a row."""
    row = {
        "content": "c",
        "heat_base": 0.25,
        "domain": "d",
        "created_at": "2026-11-15T00:00:00Z",
        "store_type": "semantic",
        "tags": '["t"]',
        "importance": 0.75,
        "surprise_score": 0.125,
        "capture_origin": "deliberate",
        "source": "post_tool_capture",
    }
    assert sqlite_store_recall._result(7, row, 0.5) == {
        "memory_id": 7,
        "content": "c",
        "score": 0.5,
        "heat": 0.25,
        "domain": "d",
        "created_at": "2026-11-15T00:00:00Z",
        "store_type": "semantic",
        "tags": ["t"],
        "importance": 0.75,
        "surprise_score": 0.125,
        "capture_origin": "deliberate",
        "source": "post_tool_capture",
    }
