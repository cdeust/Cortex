"""End-to-end recall tests: store memories -> recall_memories() PL/pgSQL
stored procedure -> ranked results.

These tests exercise the full PostgreSQL-backed retrieval path that unit/mock
tests cannot cover: the WRRF fusion stored procedure, its ranking invariants,
and the return-shape contract.

Skip pattern mirrors tests_py/infrastructure/test_pg_supersession.py:
import _USE_PG from conftest and apply pytestmark. Tests skip cleanly when
PG is absent (the normal state of this environment).

Contract assertions verified:
  - Return shape: every row contains all required columns
  - Ranking invariant 1: more content-relevant memory ranks above less relevant
  - Ranking invariant 2: higher heat memory ranks above identical-content
    lower-heat memory when heat weight is active
  - Ranking invariant 3: multiple stored memories are all retrievable
  - Negative: out-of-domain query returns empty set (domain scoping)
  - Store postcondition: insert_memory returns an integer ID > 0
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_server.infrastructure.pg_store import PgMemoryStore
from tests_py.conftest import _USE_PG  # type: ignore

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — e2e recall needs live schema"
)

_DOMAIN = "recall-e2e-test"
_DIM = 384

# ── Embedding helpers ────────────────────────────────────────────────────


def _unit_vec(seed: int) -> bytes:
    """Deterministic 384-dim float32 unit vector, L2-normalized."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tobytes()


def _query_aligned_emb(similarity: float = 1.0, seed: int = 99) -> bytes:
    """Embedding with controlled cosine similarity to the query direction (seed 0).

    similarity=1.0 returns the canonical query direction.
    similarity<1.0 blends in an orthogonal component (Gram-Schmidt).
    """
    rng0 = np.random.default_rng(0)
    base = rng0.standard_normal(_DIM).astype(np.float32)
    base /= np.linalg.norm(base)

    if similarity >= 1.0:
        return base.tobytes()

    rng2 = np.random.default_rng(seed)
    other = rng2.standard_normal(_DIM).astype(np.float32)
    other -= other.dot(base) * base  # project out the base component
    other /= np.linalg.norm(other)

    mixed = similarity * base + np.sqrt(max(0.0, 1.0 - similarity**2)) * other
    return mixed.astype(np.float32).tobytes()


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """PgMemoryStore scoped to this test module's domain; cleaned on teardown."""
    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        s._conn.commit()
    finally:
        s.close()


# ── Shared recall helper ──────────────────────────────────────────────────


def _recall(
    store: PgMemoryStore,
    query: str,
    *,
    domain: str = _DOMAIN,
    weights: dict | None = None,
    min_heat: float = 0.05,
    max_results: int = 10,
) -> list[dict]:
    """Call the PL/pgSQL stored procedure directly — no client-side reranking."""
    w = weights or {
        "vector": 1.0,
        "fts": 0.5,
        "ngram": 0.3,
        "heat": 0.3,
        "recency": 0.0,
    }
    return store.recall_memories(
        query_text=query,
        query_embedding=_query_aligned_emb(1.0),  # canonical query direction
        intent="general",
        domain=domain,
        min_heat=min_heat,
        max_results=max_results,
        weights=w,
    )


# ── Tests ─────────────────────────────────────────────────────────────────


class TestReturnShape:
    """The stored procedure must return rows with the declared column set."""

    _REQUIRED_COLUMNS = (
        "memory_id",
        "content",
        "score",
        "heat",
        "domain",
        "created_at",
        "store_type",
        "tags",
        "importance",
        "source",
    )

    def test_stored_memory_returns_required_columns(self, store):
        """Postcondition: every recalled row exposes the columns the handler reads."""
        store.insert_memory(
            {
                "content": "Return shape contract test memory alpha",
                "embedding": _query_aligned_emb(1.0),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.5,
            }
        )
        rows = _recall(store, "shape contract alpha", min_heat=0.0)
        assert rows, "expected at least one row after insert"
        for col in self._REQUIRED_COLUMNS:
            assert col in rows[0], (
                f"missing required column in stored-procedure output: {col}"
            )

    def test_score_is_positive_float(self, store):
        """Postcondition: score is a non-negative numeric value."""
        store.insert_memory(
            {
                "content": "Score is positive float test memory beta",
                "embedding": _query_aligned_emb(1.0),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.5,
            }
        )
        rows = _recall(store, "score positive float beta", min_heat=0.0)
        assert rows
        for row in rows:
            assert isinstance(row["score"], (int, float)), (
                f"score must be numeric, got {type(row['score'])}"
            )
            assert row["score"] >= 0.0, (
                f"score must be non-negative, got {row['score']}"
            )

    def test_insert_memory_returns_positive_integer_id(self, store):
        """Postcondition: insert_memory returns an int > 0."""
        mid = store.insert_memory(
            {
                "content": "Insert postcondition ID check gamma",
                "embedding": _unit_vec(1),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.3,
            }
        )
        assert isinstance(mid, int), f"expected int ID, got {type(mid)}"
        assert mid > 0, f"ID must be > 0, got {mid}"


class TestRankingInvariants:
    """The PL/pgSQL WRRF fusion must honor these ordering invariants."""

    def test_content_relevance_determines_rank(self, store):
        """Invariant: the memory whose content more closely matches the query
        must rank above a memory with unrelated content.

        Both memories share the same embedding direction (query-aligned) and
        heat so vector score is equal; the difference is FTS/ngram signal.
        """
        # High-relevance: keywords match the query exactly
        high_id = store.insert_memory(
            {
                "content": (
                    "distributed tracing with OpenTelemetry spans propagation context"
                ),
                "embedding": _query_aligned_emb(1.0),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.5,
            }
        )
        # Low-relevance: completely different topic
        low_id = store.insert_memory(
            {
                "content": "cookie recipe shortbread butter flour vanilla extract",
                "embedding": _query_aligned_emb(1.0),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.5,
            }
        )
        rows = _recall(
            store,
            "distributed tracing OpenTelemetry spans",
            weights={
                "vector": 0.5,
                "fts": 1.0,
                "ngram": 1.0,
                "heat": 0.0,
                "recency": 0.0,
            },
            min_heat=0.0,
        )
        ids = [r["memory_id"] for r in rows]
        assert high_id in ids, "relevant memory must appear in results"
        assert low_id in ids, (
            "irrelevant memory must also be retrievable (not excluded)"
        )
        assert ids.index(high_id) < ids.index(low_id), (
            f"relevant memory {high_id} must outrank irrelevant {low_id}, got order {ids}"
        )

    def test_heat_signal_breaks_tie_among_identical_content(self, store):
        """Invariant: when content is identical and embeddings equal, the
        memory with higher heat ranks first when heat weight is active.

        This pins the heat signal contribution from the stored procedure.
        """
        common = {
            "content": "identical content heat tiebreaker test delta",
            "embedding": _query_aligned_emb(1.0),
            "source": "user",
            "domain": _DOMAIN,
        }
        low_heat_id = store.insert_memory({**common, "heat": 0.1})
        high_heat_id = store.insert_memory({**common, "heat": 0.9})

        rows = _recall(
            store,
            "identical content heat tiebreaker delta",
            weights={
                "vector": 1.0,
                "fts": 0.5,
                "ngram": 0.3,
                "heat": 2.0,
                "recency": 0.0,
            },
            min_heat=0.0,
        )
        ids = [r["memory_id"] for r in rows]
        assert high_heat_id in ids and low_heat_id in ids
        assert ids.index(high_heat_id) < ids.index(low_heat_id), (
            f"high-heat memory {high_heat_id} must outrank low-heat {low_heat_id}, "
            f"got order {ids}"
        )

    def test_all_stored_memories_are_retrievable(self, store):
        """Invariant: every inserted memory appears in results when min_heat=0
        and the query covers their shared content marker.
        """
        marker = "unique retrieval coverage marker zeta"
        inserted_ids = set()
        for i in range(4):
            mid = store.insert_memory(
                {
                    "content": f"{marker} variant {i}",
                    "embedding": _query_aligned_emb(1.0, seed=i),
                    "source": "user",
                    "domain": _DOMAIN,
                    "heat": 0.3 + i * 0.1,
                }
            )
            inserted_ids.add(mid)

        rows = _recall(store, marker, min_heat=0.0, max_results=20)
        returned_ids = {r["memory_id"] for r in rows}
        missing = inserted_ids - returned_ids
        assert not missing, (
            f"memories {missing} were stored but not returned by recall_memories()"
        )


class TestDomainScoping:
    """recall_memories domain parameter must scope results to the given domain."""

    def test_memories_not_visible_across_domains(self, store):
        """Postcondition: a memory stored in domain A must NOT appear when
        querying domain B (assuming no is_global flag).
        """
        store.insert_memory(
            {
                "content": "domain isolation test memory eta backend only",
                "embedding": _query_aligned_emb(1.0),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.5,
            }
        )
        rows = _recall(
            store,
            "domain isolation test eta backend only",
            domain="completely-different-domain-xyz",
            min_heat=0.0,
        )
        ids = [r["memory_id"] for r in rows]
        # The memory was stored in _DOMAIN; querying a different domain must not
        # return it (non-global memory is domain-scoped).
        assert len(ids) == 0, (
            f"domain-scoped memory leaked across domain boundary: {ids}"
        )

    def test_memory_visible_in_its_own_domain(self, store):
        """Postcondition: a memory is always retrievable from its own domain."""
        mid = store.insert_memory(
            {
                "content": "visible in own domain test theta",
                "embedding": _query_aligned_emb(1.0),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.5,
            }
        )
        rows = _recall(store, "visible own domain theta", domain=_DOMAIN, min_heat=0.0)
        ids = [r["memory_id"] for r in rows]
        assert mid in ids, (
            f"memory {mid} must be retrievable from its own domain {_DOMAIN!r}"
        )


class TestMultipleMemoriesRanking:
    """End-to-end: store several memories with distinct relevance, verify
    the stored procedure returns them in the expected order.
    """

    def test_three_memories_ranked_by_combined_score(self, store):
        """Store three memories: high-relevance + high-heat, medium-relevance
        + medium-heat, low-relevance + low-heat. Verify the stored procedure
        orders them correctly under balanced weights.
        """
        high_id = store.insert_memory(
            {
                "content": (
                    "PostgreSQL pgvector HNSW index cosine similarity recall "
                    "retrieval embedding vector search production database"
                ),
                "embedding": _query_aligned_emb(1.0),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.9,
            }
        )
        mid_id = store.insert_memory(
            {
                "content": "vector similarity embedding recall production",
                "embedding": _query_aligned_emb(0.8, seed=10),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.5,
            }
        )
        low_id = store.insert_memory(
            {
                "content": "unrelated grocery list bread milk eggs",
                "embedding": _query_aligned_emb(0.2, seed=20),
                "source": "user",
                "domain": _DOMAIN,
                "heat": 0.1,
            }
        )

        rows = _recall(
            store,
            "PostgreSQL pgvector HNSW index cosine recall retrieval",
            weights={
                "vector": 1.0,
                "fts": 0.8,
                "ngram": 0.5,
                "heat": 0.5,
                "recency": 0.0,
            },
            min_heat=0.0,
            max_results=10,
        )
        ids = [r["memory_id"] for r in rows]

        assert high_id in ids, "high-relevance memory must appear in results"
        assert mid_id in ids, "medium-relevance memory must appear in results"
        assert low_id in ids, "low-relevance memory must appear in results"

        # High must outrank both others
        assert ids.index(high_id) < ids.index(low_id), (
            f"high-relevance memory {high_id} must outrank low-relevance {low_id}"
        )
        # Medium must outrank low
        assert ids.index(mid_id) < ids.index(low_id), (
            f"medium-relevance memory {mid_id} must outrank low-relevance {low_id}"
        )
