"""Live-PG behavior tests for explicit supersession edges (item 1).

Borrow-from-supermemory item 1: Cortex gains a nullable
``supersedes_id`` / ``superseded_by_id`` version-chain pointer on the
``memories`` table.

Read-path contract (read-path supersession PR, decision 2026-07-07,
docs/program/pr2-read-path-supersession-audit.json): superseded versions
are EXCLUDED at the source — the recall_memories candidates CTE reads the
``current_memories`` view, so a superseded fact is never served by recall.
(The Phase-1 demotion-only tier-sort proved insufficient: the demotion did
not survive client-side re-ranks, and injection channels bypassed it
entirely. The ORDER BY tier-sort is kept verbatim as a constant-true
belt-and-braces.) History stays answerable through the explicit-id
contract: ``get_memory(id)`` and the version-chain machinery still see
superseded rows.

Runs against cortex_test (conftest redirects DATABASE_URL). Calls
``store.recall_memories`` — the raw PL/pgSQL function, no client-side
reranking — so the assertions pin the stored-procedure behavior alone.
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
    not _USE_PG, reason="PostgreSQL not available — supersession needs live schema"
)

_DOMAIN = "supersession-test"
_DIM = 384


def _emb() -> bytes:
    """Deterministic 384-dim float32 unit vector aligned with the query."""
    rng = np.random.default_rng(0)
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


def _recall(store: PgMemoryStore, query: str) -> list[dict]:
    return store.recall_memories(
        query_text=query,
        query_embedding=_emb(),
        intent="general",
        domain=_DOMAIN,
        min_heat=0.05,
        max_results=10,
        weights={"vector": 1.0, "fts": 0.5, "ngram": 0.3, "heat": 0.3, "recency": 0.0},
    )


def _link(store: PgMemoryStore, *, old_id: int, new_id: int) -> None:
    """Set the version-chain edge: new_id supersedes old_id."""
    store._execute(
        "UPDATE memories SET superseded_by_id = %s WHERE id = %s", (new_id, old_id)
    )
    store._execute(
        "UPDATE memories SET supersedes_id = %s WHERE id = %s", (old_id, new_id)
    )
    store._conn.commit()


def test_recall_excludes_superseded_version(store):
    """Exclusion at the source: a superseded version never enters the
    candidate pool, even when it matches the query identically."""
    common = {
        "embedding": _emb(),
        "source": "user",
        "domain": _DOMAIN,
        "heat": 0.5,
    }
    old_id = store.insert_memory(
        {**common, "content": "deploy target is staging server one"}
    )
    new_id = store.insert_memory(
        {**common, "content": "deploy target is staging server one"}
    )
    _link(store, old_id=old_id, new_id=new_id)

    results = _recall(store, "deploy target staging server")
    ids = [r["memory_id"] for r in results]
    assert new_id in ids, f"chain head {new_id} must be served, got {ids}"
    assert old_id not in ids, (
        f"superseded version {old_id} must be excluded from recall, got {ids}"
    )


def test_superseded_retrievable_by_id_not_by_recall(store):
    """History stays answerable through the explicit-id contract, never
    through recall: when only the OLD formulation matches the query, recall
    returns a safe miss (not the retracted content), while get_memory(id)
    still serves the superseded row with its chain edge."""
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.5}
    old_id = store.insert_memory(
        {**common, "content": "unique zorblax retrieval marker"}
    )
    # A superseder that does NOT match the query keywords.
    new_id = store.insert_memory(
        {**common, "content": "completely different unrelated content"}
    )
    _link(store, old_id=old_id, new_id=new_id)

    results = _recall(store, "unique zorblax retrieval marker")
    assert old_id not in [r["memory_id"] for r in results], (
        "superseded content must never be served by recall (safe miss over "
        "serving retracted content)"
    )
    row = store.get_memory(old_id)
    assert row is not None and row["superseded_by_id"] == new_id, (
        "explicit-id read must still serve the superseded row with its edge"
    )


def test_no_edges_preserves_plain_score_order(store):
    """Benchmark-neutrality guard: with no supersession edges set, the
    tier-sort first key is constant FALSE, so order is pure fused score."""
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.5}
    high_id = store.insert_memory(
        {**common, "content": "alpha beta gamma delta epsilon marker"}
    )
    low_id = store.insert_memory({**common, "content": "alpha only marker"})

    results = _recall(store, "alpha beta gamma delta epsilon marker")
    ids = [r["memory_id"] for r in results]
    assert high_id in ids and low_id in ids
    assert ids.index(high_id) < ids.index(low_id), (
        f"no edges: stronger content match {high_id} must lead, got {ids}"
    )


def test_insert_persists_supersedes_id(store):
    """Phase 2: insert_memory now persists the forward supersedes_id edge."""
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.5}
    old_id = store.insert_memory({**common, "content": "old fact alpha"})
    new_id = store.insert_memory(
        {**common, "content": "new fact alpha", "supersedes_id": old_id}
    )
    row = store.get_memory(new_id)
    assert row is not None
    assert row["supersedes_id"] == old_id


def _open_heads(store: PgMemoryStore) -> list[int]:
    """Ids of the domain's open chain heads (superseded_by_id IS NULL)."""
    rows = store._execute(
        "SELECT id FROM memories WHERE domain = %s AND superseded_by_id IS NULL",
        (_DOMAIN,),
    ).fetchall()
    return [r["id"] for r in rows]


def test_supersede_atomic_forms_chain(store):
    """supersede_atomic inserts the new row AND stamps the head's back-pointer
    as one unit; recall then serves ONLY the current version (exclusion at
    the source), and exactly one open head remains."""
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.5}
    old_id = store.insert_memory({**common, "content": "deploy target one alpha"})

    new_id, head = store.supersede_atomic(
        {**common, "content": "deploy target one alpha"}, old_id
    )
    assert head == old_id, "target was still the head → no rebase"
    assert store.get_memory(old_id)["superseded_by_id"] == new_id
    assert store.get_memory(new_id)["supersedes_id"] == old_id
    assert _open_heads(store) == [new_id], "exactly one open head after supersession"

    results = _recall(store, "deploy target one alpha")
    ids = [r["memory_id"] for r in results]
    assert new_id in ids and old_id not in ids


def test_supersede_atomic_rebases_onto_moved_head(store):
    """Reconsolidation: correcting a fact whose chain already moved rebases the
    new row onto the CURRENT head (never forks, never disconnects). Walking
    from the original target follows superseded_by_id to the live head."""
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.5}
    old_id = store.insert_memory({**common, "content": "runner is host A"})
    mid_id, _ = store.supersede_atomic(
        {**common, "content": "runner is host B"}, old_id
    )

    # Supersede pointing at the ORIGINAL target, now mid-chain, not the head.
    new_id, head = store.supersede_atomic(
        {**common, "content": "runner is host C"}, old_id
    )
    assert head == mid_id, "rebase must land on the current head, not the stale target"
    assert store.get_memory(mid_id)["superseded_by_id"] == new_id
    assert store.get_memory(new_id)["supersedes_id"] == mid_id
    # old → mid → new, a single linear chain with one open head.
    assert store.get_memory(old_id)["superseded_by_id"] == mid_id
    assert _open_heads(store) == [new_id]


def test_supersede_atomic_conflict_rolls_back_no_orphan(store, monkeypatch):
    """Under relentless contention the bounded rebase exhausts, but because each
    attempt runs insert+edge in ONE transaction, a lost compare-and-set rolls
    the insert back: the correction is NEVER committed (no orphan) and the chain
    keeps exactly one open head. This is the core biomimetic invariant — a
    memory is never left physically disconnected."""
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.5}
    target = store.insert_memory({**common, "content": "conflict target fact"})

    real_head = store._current_chain_head
    rivals: list[int] = []

    def racing_head(conn, tid):
        # A concurrent writer supersedes the head we just found — committed on
        # a separate pooled connection — so our upcoming CAS on it will miss.
        head = real_head(conn, tid)
        if head is not None:
            rival = store.insert_memory(
                {**common, "content": f"rival {len(rivals)}", "supersedes_id": head}
            )
            store._execute(
                "UPDATE memories SET superseded_by_id = %s "
                "WHERE id = %s AND superseded_by_id IS NULL",
                (rival, head),
            )
            store._conn.commit()
            rivals.append(rival)
        return head

    monkeypatch.setattr(store, "_current_chain_head", racing_head)
    new_id, head = store.supersede_atomic(
        {**common, "content": "correction that keeps losing"}, target
    )

    assert new_id is None, "bounded rebase must exhaust under relentless contention"
    assert head is not None
    lost = store._execute(
        "SELECT id FROM memories WHERE domain = %s AND content = %s",
        (_DOMAIN, "correction that keeps losing"),
    ).fetchall()
    assert lost == [], "a lost supersession must leave NO committed row (no orphan)"
    assert len(_open_heads(store)) == 1, "the chain keeps exactly one open head"


def test_supersede_atomic_target_vanished(store):
    """A target that no longer exists yields (None, None) — nothing is
    committed, the caller learns the write did not land."""
    assert store.supersede_atomic({"content": "orphan correction"}, 2_000_000_000) == (
        None,
        None,
    )
