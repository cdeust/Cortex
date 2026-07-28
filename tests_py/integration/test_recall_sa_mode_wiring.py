"""Real-PG end-to-end test: pg_recall.recall()'s sa_mode wiring
(ADR-0054 addendum, garde x3 bench incident, 2026-07-11).

First live measurement of the SA channel (garde x3, LongMemEval) showed
the pre-fusion "augment" mode -- the one that shipped as the SA channel's
initial live behavior -- is NOT benchmark-neutral even with domain
scoping applied: MRR 0.9166->0.9009 (floor 0.914 breach) against a +0.002
R@10 gain, because LongMemEval's own ingestion creates entities INSIDE
the query's domain (8469 counted at autopsy), so domain scoping alone
does not stop "augment" from reordering already-correct top candidates.

"the guard wins; never lower the floor" (bench-before-release rule) ->
default is now "tail": append-only, never reorders, runs LAST (after
every reranking stage) so a corpus dense enough to already fill top_k
sees ZERO effect. This file proves the WIRING through the real
pg_recall.recall() entrypoint, not just the pipeline functions in
isolation (tests_py/core/test_pg_recall_pipeline.py already covers those).
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

from mcp_server.core.pg_recall import recall as pg_recall  # noqa: E402
from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: E402
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — sa_mode wiring needs live schema"
)

_DOMAIN = "sa-mode-wiring-test"
_DIM = 384


class _FixedEmbeddings:
    """Deterministic embeddings double -- avoids loading a real model in
    a unit-scoped integration test (same spirit as
    test_pg_recall_scoring_debias.py's _emb() helper, which also
    hand-builds vectors instead of running sentence-transformers)."""

    dimensions = _DIM

    def __init__(self, seed: int = 0) -> None:
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        self._vec = v.tobytes()

    def encode(self, _text: str) -> bytes:
        return self._vec


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        s._execute(
            "DELETE FROM relationships WHERE source_entity_id IN "
            "(SELECT id FROM entities WHERE name IN "
            "('SaModeAnchor', 'SaModeHidden'))"
        )
        s._execute(
            "DELETE FROM entities WHERE name IN ('SaModeAnchor', 'SaModeHidden')"
        )
        s._conn.commit()
    finally:
        s.close()


def _mk_entity(store: PgMemoryStore, name: str, *, heat: float = 0.9) -> int:
    row = store._execute(
        "INSERT INTO entities (name, type, domain, origin, heat) "
        "VALUES (%s, 'technology', %s, 'text_concept', %s) RETURNING id",
        (name, _DOMAIN, heat),
    ).fetchone()
    store._conn.commit()
    return row["id"]


def _mk_rel(store: PgMemoryStore, src: int, tgt: int) -> None:
    store._execute(
        "INSERT INTO relationships (source_entity_id, target_entity_id, "
        "relationship_type, weight, confidence) "
        "VALUES (%s, %s, 'related_to', 1.0, 1.0)",
        (src, tgt),
    )
    store._conn.commit()


class TestTailModeNeutralWhenPoolIsFull:
    """A single WRRF hit already fills top_k=1 -- tail-fill must never
    call the store, so sa_mode='tail' and sa_mode='off' must be
    bit-for-bit identical."""

    def test_tail_and_off_are_identical_when_wrrf_fills_top_k(self, store):
        mem_id = store.insert_memory(
            {
                "content": "SaModeAnchor solo match for this query",
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.9,
            }
        )
        emb = _FixedEmbeddings()
        out_tail = pg_recall(
            "SaModeAnchor solo match",
            store,
            emb,
            top_k=1,
            domain=_DOMAIN,
            sa_mode="tail",
        )
        out_off = pg_recall(
            "SaModeAnchor solo match",
            store,
            emb,
            top_k=1,
            domain=_DOMAIN,
            sa_mode="off",
        )
        assert [c["memory_id"] for c in out_tail] == [mem_id]

        # reconsolidation_apply (a REQUIRED post-WRRF stage, unrelated to
        # sa_mode) bumps heat_base on every retrieval -- calling recall()
        # twice against the same live store means the second call always
        # observes a slightly different heat than the first. That is
        # expected side effect, not an sa_mode wiring difference, so
        # "identical" is asserted on every field EXCEPT heat.
        def _strip_heat(cands):
            return [{k: v for k, v in c.items() if k != "heat"} for c in cands]

        assert _strip_heat(out_tail) == _strip_heat(out_off)


class TestTailModeFillsSparsePool:
    def test_tail_mode_appends_sa_reachable_memory_when_pool_is_short(self, store):
        anchor = _mk_entity(store, "SaModeAnchor")
        hidden = _mk_entity(store, "SaModeHidden")
        _mk_rel(store, anchor, hidden)

        mem_anchor = store.insert_memory(
            {
                "content": "SaModeAnchor solo match for this sparse-pool query",
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.9,
            }
        )
        # heat=0.08 sits BELOW the WRRF min_heat=0.1 passed to recall()
        # below (so the WRRF prefilter excludes it entirely -- it cannot
        # ride along in the heat-ranked pool the way a same-heat memory
        # would) but ABOVE spreading_activation_tail_fill's own default
        # min_heat=0.05 (so the SA entity-graph path still reaches it).
        # This isolates "reached only via SA" from "reached via WRRF's
        # broader heat pool" the same way test_spread_activation_candidate_contract.py's
        # fixture isolates it by insertion order.
        mem_hidden = store.insert_memory(
            {
                "content": "SaModeHidden note, unrelated wording entirely",
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.08,
            }
        )

        out = pg_recall(
            "SaModeAnchor solo match sparse pool query",
            store,
            _FixedEmbeddings(),
            top_k=5,
            domain=_DOMAIN,
            min_heat=0.1,
            sa_mode="tail",
        )
        ids = [c["memory_id"] for c in out]
        assert ids[0] == mem_anchor  # WRRF hit stays first, untouched
        assert mem_hidden in ids  # SA tail-fill appended it
        assert len(out) <= 5


class TestOffModeNeverCallsSpreadActivation:
    def test_off_mode_returns_short_pool_without_filling(self, store):
        anchor = _mk_entity(store, "SaModeAnchor")
        hidden = _mk_entity(store, "SaModeHidden")
        _mk_rel(store, anchor, hidden)

        mem_anchor = store.insert_memory(
            {
                "content": "SaModeAnchor solo match for this sparse-pool query",
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.9,
            }
        )
        store.insert_memory(
            {
                "content": "SaModeHidden note, unrelated wording entirely",
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.08,
            }
        )

        out = pg_recall(
            "SaModeAnchor solo match sparse pool query",
            store,
            _FixedEmbeddings(),
            top_k=5,
            domain=_DOMAIN,
            min_heat=0.1,
            sa_mode="off",
        )
        # off never fills -- only the WRRF-matched memory should surface.
        assert [c["memory_id"] for c in out] == [mem_anchor]
