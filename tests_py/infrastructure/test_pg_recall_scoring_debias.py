"""Live-PG reproduction tests for the bounded-io Phase 2 scoring fix.

Reproduces the 2026-06-10 scoring inversion (docs/provenance/bounded-io-phase2-design.md
M2): a fresh, large, keyword-rich auto-capture joined 4-5 WRRF signal pools
(content pools + mechanical heat/recency) while a month-old curated lesson
joined 1-2, so the raw dump outranked the lesson it buried. The fix excludes
``source = 'post_tool_capture'`` from the heat and recency pools (their
freshness is a write-frequency artifact, not importance) and multiplies the
final score by metamemory ``confidence`` (Kraaij, Westerveld & Hiemstra 2002
document prior; feedback-driven via rate_memory, defaults to the identity 1.0).

Runs against the cortex_test database (tests_py/conftest.py redirects
DATABASE_URL). Calls ``store.recall_memories`` — the raw PL/pgSQL function,
no client-side reranking — so the assertions pin the stored-procedure
behavior in isolation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

# Constructs PgMemoryStore() directly, so it needs a live PostgreSQL. It had no
# gate and therefore errored on any PG-less run — invisible while CI's SQLite
# job ran a single file, a hard failure once that job runs the full suite
# (#220). Gated on reachability: the subject of these tests IS the PG backend.
pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — this suite needs a live DB"
)

_DOMAIN = "scoring-debias-test"
_DIM = 384


def _emb(seed: int, similarity_to_query: float = 1.0) -> bytes:
    """Deterministic 384-dim float32 unit vector.

    ``similarity_to_query`` blends the query direction (seed 0) with an
    orthogonal direction so cosine-to-query is controlled, not random.
    """
    rng = np.random.default_rng(0)
    base = rng.standard_normal(_DIM).astype(np.float32)
    base /= np.linalg.norm(base)
    if similarity_to_query >= 1.0:
        return base.tobytes()
    other_rng = np.random.default_rng(seed)
    other = other_rng.standard_normal(_DIM).astype(np.float32)
    other -= other.dot(base) * base  # orthogonalize
    other /= np.linalg.norm(other)
    mixed = (
        similarity_to_query * base
        + np.sqrt(max(0.0, 1.0 - similarity_to_query**2)) * other
    )
    return mixed.astype(np.float32).tobytes()


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        s._conn.commit()
    finally:
        s.close()


def _recall(store: PgMemoryStore, query: str, weights: dict) -> list[dict]:
    return store.recall_memories(
        query_text=query,
        query_embedding=_emb(0),
        intent="general",
        domain=_DOMAIN,
        min_heat=0.05,
        max_results=10,
        weights=weights,
    )


class TestAutoCaptureDebias:
    def test_curated_lesson_outranks_fresh_auto_capture(self, store):
        """The Phase 2 inversion reproduction.

        The auto-capture is fresher (heat 1.0, created now), larger, and
        repeats the query keywords many times — pre-fix it topped the
        heat, recency, fts, and ngram pools simultaneously and buried
        the lesson. Post-fix it competes on content only.
        """
        lesson = (
            "Lesson: the scoring inversion root cause is WRRF rank fusion "
            "amplification across signal pools. Curated lessons must outrank "
            "raw dumps."
        )
        # A 30-day-old curated lesson is realistically CONSOLIDATED, not
        # labile: the consolidation cascade advances it long before 30 days.
        # The stage matters now that insert_memory anchors the decay clock to
        # created_at — a labile (α=2.0) memory backdated 30 days correctly
        # decays below min_heat and would be filtered. The 'consolidated'
        # stage (α=0.5, permastore floor 0.10) models the real lifecycle and
        # keeps the lesson retrievable, so this test still exercises the
        # content-debias path rather than an artificial decay-to-floor.
        # Source: A3 decay-clock anchor (pg_store.insert_memory);
        # effective_heat() stage table pg_schema.py:652-678.
        month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        curated_id = store.insert_memory(
            {
                "content": lesson,
                "embedding": _emb(0, 1.0),
                "source": "lesson",
                "domain": _DOMAIN,
                "created_at": month_ago,
                "consolidation_stage": "consolidated",
                "heat": 0.3,
            }
        )
        blob = (
            "# Tool: Bash\n**Output:**\n"
            + "scoring inversion WRRF rank fusion signal pools raw dumps\n" * 200
        )
        auto_id = store.insert_memory(
            {
                "content": blob,
                "embedding": _emb(7, 0.9),
                "source": "post_tool_capture",
                "domain": _DOMAIN,
                "heat": 1.0,
            }
        )
        results = _recall(
            store,
            "scoring inversion WRRF rank fusion",
            # heat/recency active — the exact condition that produced the
            # inversion (KNOWLEDGE_UPDATE-style weight profile).
            {"vector": 1.0, "fts": 0.5, "ngram": 0.3, "heat": 0.5, "recency": 0.5},
        )
        ids = [r["memory_id"] for r in results]
        assert curated_id in ids and auto_id in ids
        assert ids.index(curated_id) < ids.index(auto_id), (
            f"curated lesson must outrank the fresh auto-capture, got {ids}"
        )

    def test_auto_capture_still_retrievable_on_content(self, store):
        """De-bias is not exclusion: with no curated competitor the
        auto-capture still surfaces via the content pools."""
        auto_id = store.insert_memory(
            {
                "content": "# Tool: Bash\n**Output:**\n"
                "unique pgvector hnsw rebuild log",
                "embedding": _emb(0, 1.0),
                "source": "post_tool_capture",
                "domain": _DOMAIN,
                "heat": 1.0,
            }
        )
        results = _recall(
            store,
            "unique pgvector hnsw rebuild",
            {"vector": 1.0, "fts": 0.5, "ngram": 0.3, "heat": 0.5, "recency": 0.5},
        )
        assert auto_id in [r["memory_id"] for r in results]


class TestConfidencePrior:
    def test_low_confidence_ranks_below_high_confidence(self, store):
        """rate_memory feedback (metamemory confidence) must move rank."""
        common = {
            "embedding": _emb(0, 1.0),
            "source": "lesson",
            "domain": _DOMAIN,
            "heat": 0.5,
        }
        high_id = store.insert_memory(
            {**common, "content": "confidence prior test fact alpha", "confidence": 1.0}
        )
        low_id = store.insert_memory(
            {**common, "content": "confidence prior test fact alpha", "confidence": 0.2}
        )
        results = _recall(
            store,
            "confidence prior test fact alpha",
            {"vector": 1.0, "fts": 0.5, "ngram": 0.3, "heat": 0.3, "recency": 0.0},
        )
        ids = [r["memory_id"] for r in results]
        assert high_id in ids and low_id in ids
        assert ids.index(high_id) < ids.index(low_id), (
            f"confidence 1.0 must outrank confidence 0.2, got {ids}"
        )
