"""Read-path supersession regression suite — live PG.

Contract under test (read-path supersession PR, decision 2026-07-07,
docs/program/pr2-read-path-supersession-audit.json): after A is superseded
by A', the content of A is NEVER served by any content-serving read —
recall, discovery/injection channels (search_fts, search_by_tag_vector,
spread activation), shared primitives with heads_only=True, the CLS inputs
(get_episodic/semantic_memories) — while A REMAINS accessible through the
explicit-id contract (get_memory) and the chain machinery, and maintenance
reads (heads_only=False) keep seeing physical rows.

Anchor transfer (decision 2026-07-07): a protected/anchored memory that
gets superseded hands its protection flags and heat pin to the new head
inside the supersede transaction.

Every test writes A, supersedes A→A', then asserts on both sides of the
contract. Runs against cortex_test (conftest redirects DATABASE_URL).
"""

from __future__ import annotations

import numpy as np
import pytest


# psycopg ships in the optional [postgresql] extra, absent from the
# SQLite-default install. The mcp_server import below pulls it in, so
# without this guard the module raises ModuleNotFoundError at COLLECTION
# time — an error, not a skip, which fails the whole run (#220). Skip the
# module cleanly instead; the PG gate below still applies when it is present.
pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: E402
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — read-path needs live schema"
)

_DOMAIN = "supersession-read-path-test"
_DIM = 384


def _emb(seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    base = rng.standard_normal(_DIM).astype(np.float32)
    base /= np.linalg.norm(base)
    return base.tobytes()


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        s._conn.commit()
    finally:
        s.close()


def _supersede_pair(
    store: PgMemoryStore,
    old_content: str,
    new_content: str,
    **extra,
) -> tuple[int, int]:
    """Insert old, supersede with new via the atomic write path."""
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.5}
    common.update(extra)
    old_id = store.insert_memory({**common, "content": old_content})
    new_id, head = store.supersede_atomic({**common, "content": new_content}, old_id)
    assert new_id is not None and head == old_id
    return old_id, new_id


# ── Injection / discovery channels ──────────────────────────────────────


def test_search_fts_excludes_superseded(store):
    old_id, new_id = _supersede_pair(
        store, "trigger marker fact old", "trigger marker fact new"
    )
    ids = [mid for mid, _ in store.search_fts("trigger marker fact", limit=20)]
    assert new_id in ids and old_id not in ids


def test_search_fts_excludes_stale(store):
    mid = store.insert_memory(
        {
            "content": "stale trigger marker fact",
            "embedding": _emb(),
            "domain": _DOMAIN,
            "heat": 0.5,
        }
    )
    store.mark_memory_stale(mid)
    ids = [m for m, _ in store.search_fts("stale trigger marker", limit=20)]
    assert mid not in ids


def test_search_by_tag_vector_excludes_superseded(store):
    old_id, new_id = _supersede_pair(
        store,
        "user instruction always use tabs",
        "user instruction always use spaces",
        tags=["instruction"],
    )
    # Vector branch
    rows = store.search_by_tag_vector(_emb(), "instruction", min_heat=0.0, limit=10)
    ids = [r["id"] for r in rows]
    assert new_id in ids and old_id not in ids
    # Heat-ordered branch (no embedding)
    rows = store.search_by_tag_vector(None, "instruction", min_heat=0.0, limit=10)
    ids = [r["id"] for r in rows]
    assert new_id in ids and old_id not in ids


def test_search_vectors_heads_only(store):
    old_id, new_id = _supersede_pair(store, "vector fact old", "vector fact new")
    heads = [m for m, _ in store.search_vectors(_emb(), top_k=10, heads_only=True)]
    assert new_id in heads and old_id not in heads
    # Default (maintenance callers) keeps seeing physical rows.
    all_rows = [m for m, _ in store.search_vectors(_emb(), top_k=10)]
    assert old_id in all_rows


# ── Shared primitives: heads_only routing ───────────────────────────────


def test_get_memories_for_domain_heads_only(store):
    old_id, new_id = _supersede_pair(store, "domain fact old", "domain fact new")
    heads = [
        m["id"]
        for m in store.get_memories_for_domain(_DOMAIN, min_heat=0.0, heads_only=True)
    ]
    assert new_id in heads and old_id not in heads
    # Maintenance default sees the full chain.
    full = [m["id"] for m in store.get_memories_for_domain(_DOMAIN, min_heat=0.0)]
    assert old_id in full and new_id in full


def test_get_hot_memories_heads_only(store):
    old_id, new_id = _supersede_pair(store, "hot fact old", "hot fact new")
    heads = [
        m["id"] for m in store.get_hot_memories(min_heat=0.0, limit=0, heads_only=True)
    ]
    assert new_id in heads and old_id not in heads


def test_get_memories_mentioning_entity_heads_only(store):
    old_id, new_id = _supersede_pair(
        store, "zorbafact entity old version", "zorbafact entity new version"
    )
    # FTS branch
    heads = [
        m["id"]
        for m in store.get_memories_mentioning_entity("zorbafact", heads_only=True)
    ]
    assert new_id in heads and old_id not in heads
    # ILIKE fallback branch (term absent from the FTS lexeme match)
    heads = [
        m["id"]
        for m in store.get_memories_mentioning_entity("orbafac", heads_only=True)
    ]
    assert old_id not in heads


def test_get_recently_accessed_memories_heads_only(store):
    old_id, new_id = _supersede_pair(store, "accessed fact old", "accessed fact new")
    store._execute(
        "UPDATE memories SET access_count = 5 WHERE id IN (%s, %s)", (old_id, new_id)
    )
    store._conn.commit()
    heads = [
        m["id"] for m in store.get_recently_accessed_memories(limit=50, heads_only=True)
    ]
    assert new_id in heads and old_id not in heads


# ── CLS inputs ──────────────────────────────────────────────────────────


def test_get_episodic_memories_excludes_superseded(store):
    old_id, new_id = _supersede_pair(store, "episodic fact old", "episodic fact new")
    ids = [m["id"] for m in store.get_episodic_memories(domain=_DOMAIN)]
    assert new_id in ids and old_id not in ids


def test_get_semantic_memories_excludes_superseded(store):
    old_id, new_id = _supersede_pair(
        store, "semantic fact old", "semantic fact new", store_type="semantic"
    )
    ids = [m["id"] for m in store.get_semantic_memories(domain=_DOMAIN)]
    assert new_id in ids and old_id not in ids


# ── Explicit-id contract: history stays answerable ──────────────────────


def test_superseded_row_stays_readable_by_id(store):
    old_id, new_id = _supersede_pair(store, "history fact old", "history fact new")
    row = store.get_memory(old_id)
    assert row is not None
    assert row["content"] == "history fact old"
    assert row["superseded_by_id"] == new_id
    assert store.get_memory(new_id)["supersedes_id"] == old_id


# ── Anchor follows the head ─────────────────────────────────────────────


def test_anchor_transfers_to_new_head(store):
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.5}
    old_id = store.insert_memory({**common, "content": "anchored fact old"})
    store._execute(
        "UPDATE memories SET heat_base = 1.0, no_decay = TRUE, "
        "is_protected = TRUE WHERE id = %s",
        (old_id,),
    )
    store._conn.commit()

    new_id, _ = store.supersede_atomic(
        {**common, "content": "anchored fact new"}, old_id
    )
    head = store.get_memory(new_id)
    assert head["is_protected"] is True
    assert head["no_decay"] is True
    assert head["heat_base"] == pytest.approx(1.0)


def test_no_anchor_transfer_for_unprotected_head(store):
    old_id, new_id = _supersede_pair(store, "plain fact old", "plain fact new")
    head = store.get_memory(new_id)
    assert head["is_protected"] is False
    assert head["no_decay"] is False
