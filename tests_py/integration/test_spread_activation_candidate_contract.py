"""Real-PG contract test: SA-injected candidates vs WRRF candidates.

Incident 2026-07-11 (garde x3 bench, LongMemEval, PID 99074): the first
recall() call with EVENT_ORDER intent crashed --
``TypeError: '<' not supported between instances of 'str' and
'datetime.datetime'`` at ``pg_recall.py::_chronological_rerank``'s
``sorted(candidates, key=lambda c: c.get("created_at", ""))``.

Root cause, verified against the real PL/pgSQL + psycopg types (not
inferred from the log alone -- see ADR-0054 addendum for the full trace):
``store.recall_memories()`` (WRRF path) returned raw
``dict(r)`` rows, leaving ``created_at`` a psycopg
``datetime.datetime`` object; ``store.get_memory()`` (used by
``spreading_activation_expand`` to build SA-injected candidates) already
normalized it to an ISO string via ``_normalize_memory_row``. The two
candidate types could never collide before SA was alive (WITH RECURSIVE
was broken, ADR-0054 §1) -- one query's candidate list came from exactly
one source. Once SA started actually injecting rows, a single list held
both types and ``sorted()`` raised.

Two bugs, one root: the SA-injection point built its candidate dict from
a curated 6-field subset of ``store.get_memory()``'s row instead of the
full WRRF contract (``recall_memories()``'s RETURNS TABLE: memory_id,
content, score, heat, domain, created_at, store_type, tags, importance,
surprise_score, emotional_valence, source, value, source_attribution).
That silently dropped store_type/source/source_attribution/importance/
surprise_score/emotional_valence/value from every SA-injected candidate
-- e.g. ``recall_helpers.py``'s low-signal filter keys on
``mem.get("source") == "post_tool_capture"``; a missing key always reads
as ``None``, so an SA-injected auto-capture could never be filtered as
low-signal, regardless of its real source.

Fix (mcp_server/core/recall_pipeline.py::spreading_activation_expand,
mcp_server/infrastructure/pg_store.py::recall_memories/_isoformat_datetime_fields):
both readers now normalize created_at through the same helper, and the
SA-injection dict is built as an explicit whitelist mirroring the WRRF
contract's full field set (not a superset either -- get_memory() returns
every ``memories`` column, including internal state like
compression_level/write_class/superseded_by_id that must NOT leak into a
candidate dict).

This file is the contract test that would have caught both bugs before
merge: it runs the real PL/pgSQL functions (recall_memories,
spread_activation_memories) and compares the resulting candidate dicts
key-for-key, type-for-type.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest


# psycopg ships in the optional [postgresql] extra, absent from the
# SQLite-default install. The mcp_server import below pulls it in, so
# without this guard the module raises ModuleNotFoundError at COLLECTION
# time — an error, not a skip, which fails the whole run (#220). Skip the
# module cleanly instead; the PG gate below still applies when it is present.
pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from mcp_server.core.pg_recall import _chronological_rerank  # noqa: E402
from mcp_server.core.recall_pipeline import spreading_activation_expand  # noqa: E402
from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: E402
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG,
    reason="PostgreSQL not available — candidate-contract test needs live schema",
)

_DOMAIN = "sa-candidate-contract-test"
_DIM = 384

# The exact RETURNS TABLE column set of recall_memories() (pg_schema.py's
# RECALL_MEMORIES_LAZY_FN) -- the ground-truth WRRF candidate contract.
_WRRF_CONTRACT_FIELDS = {
    "memory_id",
    "content",
    "score",
    "heat",
    "domain",
    "created_at",
    "store_type",
    "tags",
    "importance",
    "surprise_score",
    "emotional_valence",
    "source",
    "value",
    "source_attribution",
}


def _query_emb() -> bytes:
    rng = np.random.default_rng(0)
    v = rng.standard_normal(_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tobytes()


def _unrelated_emb() -> bytes:
    """A random embedding with no engineered similarity to the query
    direction -- keeps the SA-only memory out of the WRRF top-K."""
    rng = np.random.default_rng(777)
    v = rng.standard_normal(_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tobytes()


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        s._execute(
            "DELETE FROM relationships WHERE source_entity_id IN "
            "(SELECT id FROM entities WHERE name IN "
            "('ContractProbeAnchor', 'ContractProbeHidden'))"
        )
        s._execute(
            "DELETE FROM entities WHERE name IN "
            "('ContractProbeAnchor', 'ContractProbeHidden')"
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


@pytest.fixture
def wrrf_and_sa_candidates(store: PgMemoryStore):
    """Build a real WRRF candidate (M1, direct match) plus a real
    SA-only-reachable candidate (M2, via an entity-graph edge from M1's
    entity), and return (wrrf_candidate, expanded_candidates).

    M2 is inserted AFTER the WRRF call (recall_memories over-fetches 3x
    max_results, pg_store.py::recall_memories docstring -- a heat-tied
    M2 present at query time could ride along in that broader pool and
    make the WRRF-only/SA-only split ambiguous). Inserting M2 only after
    the WRRF snapshot guarantees it reaches `expanded` through exactly
    one path: spreading_activation_expand's injection.
    """
    anchor = _mk_entity(store, "ContractProbeAnchor")
    hidden = _mk_entity(store, "ContractProbeHidden")
    _mk_rel(store, anchor, hidden)

    mem_wrrf = store.insert_memory(
        {
            "content": "ContractProbeAnchor note: what happened first in the "
            "sequence of events here",
            "source": "user",
            "domain": _DOMAIN,
            "heat": 0.9,
        }
    )

    wrrf_candidates = store.recall_memories(
        query_text="ContractProbeAnchor what happened first sequence of events",
        query_embedding=_query_emb(),
        domain=_DOMAIN,
        min_heat=0.0,
        max_results=1,
    )
    assert [c["memory_id"] for c in wrrf_candidates] == [mem_wrrf]

    mem_sa_only = store.insert_memory(
        {
            "content": "ContractProbeHidden note, unrelated wording entirely",
            "source": "post_tool_capture",
            "domain": _DOMAIN,
            "heat": 0.9,
        }
    )

    expanded = spreading_activation_expand(
        wrrf_candidates,
        "ContractProbeAnchor what happened first sequence of events",
        store,
        domain=_DOMAIN,
        min_heat=0.0,
    )
    return mem_wrrf, mem_sa_only, expanded


class TestFieldContract:
    def test_sa_injection_actually_happened(self, wrrf_and_sa_candidates):
        """Sanity: the fixture's graph topology must produce a real
        injection, or every assertion below is vacuous."""
        _mem_wrrf, mem_sa_only, expanded = wrrf_and_sa_candidates
        ids = [c["memory_id"] for c in expanded]
        assert mem_sa_only in ids

    def test_injected_candidate_key_set_matches_wrrf_contract(
        self, wrrf_and_sa_candidates
    ):
        mem_wrrf, mem_sa_only, expanded = wrrf_and_sa_candidates
        by_id = {c["memory_id"]: c for c in expanded}
        wrrf_keys = set(by_id[mem_wrrf].keys())
        sa_keys = set(by_id[mem_sa_only].keys()) - {"_sa_injected"}
        assert wrrf_keys == _WRRF_CONTRACT_FIELDS
        assert sa_keys == _WRRF_CONTRACT_FIELDS

    def test_injected_candidate_field_types_match_wrrf_candidate(
        self, wrrf_and_sa_candidates
    ):
        """Type-for-type comparison — the actual assertion the 2026-07-11
        crash needed. None is accepted as a wildcard (source_attribution
        is NULLable on both paths)."""
        mem_wrrf, mem_sa_only, expanded = wrrf_and_sa_candidates
        by_id = {c["memory_id"]: c for c in expanded}
        wrrf_c, sa_c = by_id[mem_wrrf], by_id[mem_sa_only]
        for field in _WRRF_CONTRACT_FIELDS:
            wv, sv = wrrf_c[field], sa_c[field]
            if wv is None or sv is None:
                continue
            assert type(wv) is type(sv), (
                f"field {field!r}: WRRF type {type(wv).__name__} != "
                f"SA-injected type {type(sv).__name__}"
            )

    def test_created_at_is_never_a_raw_datetime(self, wrrf_and_sa_candidates):
        """The exact field that crashed. Both paths must yield str."""
        _mem_wrrf, _mem_sa_only, expanded = wrrf_and_sa_candidates
        for c in expanded:
            assert not isinstance(c["created_at"], datetime)
            assert isinstance(c["created_at"], str)

    def test_source_field_is_preserved_for_low_signal_filtering(
        self, wrrf_and_sa_candidates
    ):
        """Regression for the silently-dropped `source` field: an
        SA-injected candidate whose real source is post_tool_capture must
        still report that source, not silently default to something the
        low-signal filter (recall_helpers.py) treats as curated."""
        _mem_wrrf, mem_sa_only, expanded = wrrf_and_sa_candidates
        by_id = {c["memory_id"]: c for c in expanded}
        assert by_id[mem_sa_only]["source"] == "post_tool_capture"


class TestDownstreamConsumers:
    """Inventory of every recall_pipeline.py/pg_recall.py stage downstream
    of spreading_activation_expand that reads a candidate field the SA
    injection could plausibly get wrong. Each assertion below exercises
    the REAL consumer function against the REAL mixed candidate list."""

    def test_chronological_rerank_survives_mixed_candidate_list(
        self, wrrf_and_sa_candidates
    ):
        """The exact crash site: pg_recall.py::_chronological_rerank on
        an EVENT_ORDER query's merged WRRF+SA candidate list."""
        _mem_wrrf, _mem_sa_only, expanded = wrrf_and_sa_candidates
        assert len(expanded) > 1  # sort only runs when len > 1 (pg_recall.py:499)
        out = _chronological_rerank(list(expanded), beta=0.5, k=60)
        assert len(out) == len(expanded)

    def test_value_priority_rerank_survives_mixed_candidate_list(
        self, wrrf_and_sa_candidates
    ):
        from mcp_server.core.recall_pipeline import value_priority_rerank

        _mem_wrrf, _mem_sa_only, expanded = wrrf_and_sa_candidates
        out = value_priority_rerank(list(expanded))
        assert len(out) == len(expanded)

    def test_emotional_retrieval_rerank_survives_mixed_candidate_list(
        self, wrrf_and_sa_candidates
    ):
        from mcp_server.core.recall_pipeline import emotional_retrieval_rerank

        _mem_wrrf, _mem_sa_only, expanded = wrrf_and_sa_candidates
        out = emotional_retrieval_rerank(
            list(expanded), "what happened first, this made me happy and excited"
        )
        assert len(out) == len(expanded)

    def test_dendritic_modulate_survives_mixed_candidate_list(
        self, wrrf_and_sa_candidates
    ):
        from mcp_server.core.recall_pipeline import dendritic_modulate

        _mem_wrrf, _mem_sa_only, expanded = wrrf_and_sa_candidates
        out = dendritic_modulate(
            list(expanded), "ContractProbeAnchor what happened first"
        )
        assert len(out) == len(expanded)
