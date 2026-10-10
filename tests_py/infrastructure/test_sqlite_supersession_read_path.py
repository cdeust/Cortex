"""Read-path supersession regression suite — SQLite parity.

Mirror of test_supersession_read_path.py for the SQLite backend
(decision 2026-07-07, docs/program/pr2-read-path-supersession-audit.json):
after A is superseded by A', A's content is never served by the
content-serving reads (client-side WRRF recall, search_fts join,
heads_only primitives, CLS inputs), while get_memory(id) keeps serving it
and the anchor transfer hands protection to the new head.

No skip: SqliteMemoryStore is constructed directly (stdlib sqlite3,
in-memory), independent of the CI backend env.
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_DOMAIN = "supersession-read-path-test"


@pytest.fixture
def store():
    return SqliteMemoryStore()


def _supersede_pair(
    store: SqliteMemoryStore,
    old_content: str,
    new_content: str,
    **extra,
) -> tuple[int, int]:
    common = {"source": "user", "domain": _DOMAIN, "heat": 0.5}
    common.update(extra)
    old_id = store.insert_memory({**common, "content": old_content})
    new_id, head = store.supersede_atomic({**common, "content": new_content}, old_id)
    assert new_id is not None and head == old_id
    return old_id, new_id


def test_view_serves_heads_only(store):
    old_id, new_id = _supersede_pair(store, "view fact old", "view fact new")
    heads = [
        r["id"]
        for r in store._conn.execute("SELECT id FROM current_memories").fetchall()
    ]
    assert new_id in heads and old_id not in heads


def test_recall_memories_excludes_superseded(store):
    old_id, new_id = _supersede_pair(
        store, "recall marker fact old", "recall marker fact new"
    )
    results = store.recall_memories(
        "recall marker fact", None, min_heat=0.0, max_results=10
    )
    ids = [r["memory_id"] for r in results]
    assert new_id in ids and old_id not in ids


def test_search_fts_excludes_superseded_and_stale(store):
    old_id, new_id = _supersede_pair(
        store, "trigger marker fact old", "trigger marker fact new"
    )
    stale_id = store.insert_memory(
        {"content": "trigger marker fact stale", "domain": _DOMAIN, "heat": 0.5}
    )
    store.mark_memory_stale(stale_id)
    ids = [mid for mid, _ in store.search_fts("trigger marker fact", limit=20)]
    assert new_id in ids
    assert old_id not in ids
    assert stale_id not in ids


def test_spread_activation_mapping_excludes_superseded(store):
    """_map_entities_to_memories reads current_memories: a superseded row
    reachable through the entity graph must not be re-injected."""
    old_id, new_id = _supersede_pair(
        store, "zorbaproj deploy old", "zorbaproj deploy new"
    )
    eid = store.insert_entity(
        {"name": "zorbaproj", "type": "project", "domain": _DOMAIN}
    )
    acts = store._map_entities_to_memories({eid: 1.0}, min_heat=0.0, max_results=20)
    ids = [mid for mid, _ in acts]
    assert new_id in ids and old_id not in ids


def test_get_memories_for_domain_heads_only(store):
    old_id, new_id = _supersede_pair(store, "domain fact old", "domain fact new")
    heads = [
        m["id"]
        for m in store.get_memories_for_domain(_DOMAIN, min_heat=0.0, heads_only=True)
    ]
    assert new_id in heads and old_id not in heads
    full = [
        m["id"]
        for m in store.get_memories_for_domain(_DOMAIN, min_heat=0.0, heads_only=False)
    ]
    assert old_id in full


def test_get_hot_memories_heads_only(store):
    old_id, new_id = _supersede_pair(store, "hot fact old", "hot fact new")
    heads = [
        m["id"] for m in store.get_hot_memories(min_heat=0.0, limit=50, heads_only=True)
    ]
    assert new_id in heads and old_id not in heads


def test_get_memories_mentioning_entity_heads_only(store):
    old_id, new_id = _supersede_pair(
        store, "zorbafact entity old", "zorbafact entity new"
    )
    heads = [
        m["id"]
        for m in store.get_memories_mentioning_entity("zorbafact", heads_only=True)
    ]
    assert new_id in heads and old_id not in heads


def test_get_recently_accessed_memories_heads_only(store):
    old_id, new_id = _supersede_pair(store, "accessed fact old", "accessed fact new")
    store._conn.execute(
        "UPDATE memories SET access_count = 5 WHERE id IN (?, ?)", (old_id, new_id)
    )
    store._conn.commit()
    heads = [
        m["id"] for m in store.get_recently_accessed_memories(limit=50, heads_only=True)
    ]
    assert new_id in heads and old_id not in heads


def test_cls_inputs_exclude_superseded(store):
    old_id, new_id = _supersede_pair(store, "episodic fact old", "episodic fact new")
    ids = [m["id"] for m in store.get_episodic_memories(domain=_DOMAIN)]
    assert new_id in ids and old_id not in ids

    old_s, new_s = _supersede_pair(
        store, "semantic fact old", "semantic fact new", store_type="semantic"
    )
    ids = [m["id"] for m in store.get_semantic_memories(domain=_DOMAIN)]
    assert new_s in ids and old_s not in ids


def test_superseded_row_stays_readable_by_id(store):
    old_id, new_id = _supersede_pair(store, "history fact old", "history fact new")
    row = store.get_memory(old_id)
    assert row is not None
    assert row["content"] == "history fact old"
    assert row["superseded_by_id"] == new_id


def test_anchor_transfers_to_new_head(store):
    old_id = store.insert_memory(
        {"content": "anchored fact old", "domain": _DOMAIN, "heat": 0.5}
    )
    store._conn.execute(
        "UPDATE memories SET heat_base = 1.0, no_decay = 1, is_protected = 1 "
        "WHERE id = ?",
        (old_id,),
    )
    store._conn.commit()

    new_id, _ = store.supersede_atomic(
        {"content": "anchored fact new", "domain": _DOMAIN, "heat": 0.4}, old_id
    )
    head = store.get_memory(new_id)
    assert bool(head["is_protected"]) is True
    assert bool(head["no_decay"]) is True
    assert head["heat_base"] == pytest.approx(1.0)


def test_no_anchor_transfer_for_unprotected_head(store):
    _old_id, new_id = _supersede_pair(store, "plain fact old", "plain fact new")
    head = store.get_memory(new_id)
    assert not head["is_protected"]
    assert not head["no_decay"]
