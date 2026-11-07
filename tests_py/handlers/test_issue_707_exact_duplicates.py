"""Issue #707: exact replays and legacy cleanup through real persistence."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from mcp_server.handlers import consolidate, remember
from mcp_server.hooks import capture_store
from mcp_server.infrastructure.memory_exact import collapse_exact, insert_exact
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture(params=["configured", "sqlite"])
def store(request, tmp_path):
    if request.param == "configured":
        yield remember._get_store()
    else:
        backend = SqliteMemoryStore(str(tmp_path / "duplicates.db"))
        try:
            yield backend
        finally:
            backend.close()


@pytest.mark.parametrize("write_class", ["deliberate", "auto"])
def test_seven_identical_writes_leave_one_row(store, monkeypatch, write_class):
    monkeypatch.setattr(remember, "_store", store)
    args = {
        "content": "Error: issue 707 exact capture replay",
        "tags": [],
        "directory": "",
        "write_class": write_class,
        "force": write_class == "deliberate",
        "source": "user" if write_class == "deliberate" else "post_tool_capture",
        "origin_tool": "" if write_class == "deliberate" else "Bash",
    }
    handler = capture_store.store if write_class == "auto" else remember.handler
    results = [asyncio.run(handler(dict(args))) for _ in range(7)]
    assert results[0]["stored"] is True
    assert all(r["reason"] == "exact_duplicate" for r in results[1:])
    assert all(r["stored"] is False for r in results[1:])
    assert {r["memory_id"] for r in results} == {results[0]["memory_id"]}
    rows = store._execute(
        "SELECT id FROM memories WHERE content = %s", (args["content"],)
    ).fetchall()
    assert len(rows) == 1


def test_duplicate_preflight_does_not_load_encoder(store, monkeypatch):
    monkeypatch.setattr(remember, "_store", store)
    args = {"content": "Issue 707 deliberate duplicate", "force": True}
    first = asyncio.run(remember.handler(dict(args)))

    def unexpected_encoder():
        pytest.fail("exact duplicate loaded encoder")

    monkeypatch.setattr(remember, "get_embedding_engine", unexpected_encoder)
    replay = asyncio.run(remember.handler(dict(args)))
    assert replay == {
        "stored": False,
        "action": "rejected",
        "reason": "exact_duplicate",
        "memory_id": first["memory_id"],
    }


def test_atomic_insertion_serializes_two_writers(store):
    barrier = Barrier(2)
    data = {"content": "Issue 707 simultaneous replay"}

    def write():
        barrier.wait()
        return insert_exact(store, dict(data))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: write(), range(2)))
    assert len({mid for mid, _ in results}) == 1
    assert sorted(inserted for _, inserted in results) == [False, True]


@pytest.mark.parametrize(
    "field,value",
    [
        ("domain", "another-domain"),
        ("directory_context", "/another-project"),
        ("agent_context", "another-agent"),
        ("source", "another-source"),
        ("write_class", "auto"),
        ("capture_origin", "deliberate"),
        ("is_global", True),
        ("is_team_decision", True),
    ],
)
def test_equal_text_keeps_distinct_scope(store, field, value):
    first, inserted = insert_exact(store, {"content": "scope isolation"})
    second, separate = insert_exact(store, {"content": "scope isolation", field: value})
    assert inserted and separate
    assert first != second
    assert collapse_exact(store) == {"superseded_total": 0}


def test_legacy_duplicates_collapse_and_second_pass_is_quiet(store, monkeypatch):
    ids = [store.insert_memory({"content": "legacy identical rows"}) for _ in range(7)]
    monkeypatch.setattr(consolidate, "_store", store)
    monkeypatch.setattr(consolidate, "get_embedding_engine", lambda: None)
    result = asyncio.run(
        consolidate.handler(
            {
                "decay": False,
                "compress": False,
                "cls": False,
                "memify": False,
                "wiki": False,
            }
        )
    )
    assert result["exact_duplicates"]["superseded_total"] == 6
    rows = store._execute(
        "SELECT id, superseded_by_id FROM memories WHERE content = %s",
        ("legacy identical rows",),
    ).fetchall()
    heads = [r["id"] for r in rows if r["superseded_by_id"] is None]
    assert len(heads) == 1
    assert set(r["id"] for r in rows) == set(ids)
    assert all(r["superseded_by_id"] == heads[0] for r in rows if r["id"] != heads[0])
    assert collapse_exact(store) == {"superseded_total": 0}


def test_exact_means_case_and_whitespace_are_preserved(store):
    values = ["Exact text", "exact text", "Exact  text"]
    results = [insert_exact(store, {"content": text}) for text in values]
    assert all(inserted for _, inserted in results)
    assert len({mid for mid, _ in results}) == len(values)
    assert collapse_exact(store) == {"superseded_total": 0}


def test_path_identified_state_replicas_remain_separate(store):
    results = [
        insert_exact(
            store,
            {
                "content": "identical block state",
                "tags": ["memory-replica", f"vpath:{path}"],
            },
        )
        for path in ("first.md", "second.md")
    ]
    assert all(inserted for _, inserted in results)
    assert len({mid for mid, _ in results}) == 2
    assert collapse_exact(store) == {"superseded_total": 0}


def test_consolidation_preserves_every_protection_flag(store):
    protected = store.insert_memory(
        {
            "content": "protected duplicate",
            "is_protected": True,
        }
    )
    frozen = store.insert_memory({"content": "protected duplicate"})
    store._execute("UPDATE memories SET no_decay = TRUE WHERE id = %s", (frozen,))
    store._conn.commit()
    assert collapse_exact(store) == {"superseded_total": 1}
    survivor = store.get_memory(protected)
    assert survivor["is_protected"]
    assert survivor["no_decay"]
    assert store.get_memory(frozen)["superseded_by_id"] == protected
