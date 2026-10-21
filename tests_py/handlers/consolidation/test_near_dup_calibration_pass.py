"""Integration tests for handlers.consolidation.near_dup_calibration_pass
(I6-D2, INC6.4) — live PG (``cortex_test`` via conftest), same convention
as ``test_memory_dedup_exact_pass.py``.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from mcp_server.handlers.consolidation.near_dup_calibration_pass import (
    run_near_dup_apply_pass,
    run_near_dup_sample,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from tests_py._pg_hnsw import empty_memories_index

# source: ADR-1112 (tests of the store itself run on the in-process store)
pytestmark = pytest.mark.in_process_store

EMBEDDING_DIM = 384


def _store():
    s = get_memory_settings()
    return get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)


def _pg_only():
    store = _store()
    if not hasattr(store, "batch_pool"):
        pytest.skip("near_dup_calibration_pass requires a PostgreSQL store")
    return store


def _unit_vector(nonzero_index: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[nonzero_index] = 1.0
    return v


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(x) for x in values) + "]"


def _unique_content(label: str) -> str:
    return f"I6-D2 near-dup handler test [{label}] {uuid.uuid4().hex}"


def _insert(
    conn, *, content: str, embedding: list[float], heat_base: float = 0.5
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memories
                   (content, embedding, tags, source, heat_base, no_decay)
               VALUES (%(content)s, %(embedding)s::vector, %(tags)s::jsonb,
                       'test', %(heat_base)s, TRUE)
               RETURNING id""",
            {
                "content": content,
                "embedding": _vector_literal(embedding),
                "tags": json.dumps([]),
                "heat_base": heat_base,
            },
        )
        return cur.fetchone()["id"]


def _fetch_superseded_by(conn, memory_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT superseded_by_id FROM memories WHERE id = %s", (memory_id,))
        row = cur.fetchone()
        return row["superseded_by_id"] if isinstance(row, dict) else row[0]


@pytest.fixture(autouse=True)
def _empty_hnsw_index():
    """Each test asserts on the HNSW top-K: start from an empty index
    (tests_py/_pg_hnsw.py)."""
    store = _store()
    if hasattr(store, "batch_pool"):
        with store.batch_pool.connection() as conn:
            empty_memories_index(conn)


class TestRunNearDupSample:
    def test_sample_includes_seeded_pair_with_contents(self):
        store = _pg_only()
        vec = _unit_vector(50)
        content_a = _unique_content("sample-a")
        content_b = _unique_content("sample-b")
        with store.batch_pool.connection() as conn:
            id_a = _insert(conn, content=content_a, embedding=vec)
            id_b = _insert(conn, content=content_b, embedding=vec)
            conn.commit()
        try:
            result = asyncio.run(
                run_near_dup_sample(
                    store, top_k=10, min_similarity=0.75, per_stratum=50
                )
            )
            assert result["status"] == "ok"
            matched = [
                s for s in result["sample"] if {s["id_a"], s["id_b"]} == {id_a, id_b}
            ]
            assert len(matched) == 1
            assert matched[0]["content_a"] in (content_a, content_b)
            assert matched[0]["content_b"] in (content_a, content_b)
            assert matched[0]["similarity"] == pytest.approx(1.0, abs=1e-4)
            # Histogram accounts for the seeded pair in the top stratum.
            assert result["histogram"].get("0.95-1.00", 0) >= 1
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = ANY(%s)", ([id_a, id_b],))
                conn.commit()


class TestRunNearDupApplyPass:
    def test_pairs_above_threshold_collapse_onto_hottest_member(self):
        store = _pg_only()
        vec = _unit_vector(60)
        with store.batch_pool.connection() as conn:
            cold_id = _insert(
                conn,
                content=_unique_content("apply-cold"),
                embedding=vec,
                heat_base=0.1,
            )
            hot_id = _insert(
                conn, content=_unique_content("apply-hot"), embedding=vec, heat_base=0.9
            )
            conn.commit()
        try:
            result = asyncio.run(
                run_near_dup_apply_pass(
                    store, threshold=0.90, apply=True, top_k=10, min_similarity=0.75
                )
            )
            assert result["status"] == "ok"
            group = next(
                (j for j in result["journal"] if j["survivor_id"] == hot_id),
                None,
            )
            assert group is not None
            assert cold_id in group["superseded_ids"]

            with store.batch_pool.connection() as conn:
                assert _fetch_superseded_by(conn, cold_id) == hot_id
                assert _fetch_superseded_by(conn, hot_id) is None
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)", ([cold_id, hot_id],)
                )
                conn.commit()

    def test_pairs_below_threshold_go_to_review_queue_not_superseded(self):
        store = _pg_only()
        # Two vectors close but not identical: place both in the
        # 0.75-0.90 gap by mixing two axes at a fixed ratio.
        vec_a = _unit_vector(70)
        vec_b = [0.0] * EMBEDDING_DIM
        vec_b[70] = 0.8
        vec_b[71] = 0.6  # cos(a,b) = 0.8 -- below the 0.90 threshold, above 0.75 floor
        with store.batch_pool.connection() as conn:
            id_a = _insert(conn, content=_unique_content("review-a"), embedding=vec_a)
            id_b = _insert(conn, content=_unique_content("review-b"), embedding=vec_b)
            conn.commit()
        try:
            result = asyncio.run(
                run_near_dup_apply_pass(
                    store, threshold=0.90, apply=True, top_k=10, min_similarity=0.75
                )
            )
            assert result["status"] == "ok"
            review_pair = [
                p
                for p in result["review_queue"]
                if {p["id_a"], p["id_b"]} == {id_a, id_b}
            ]
            assert len(review_pair) == 1
            assert 0.75 <= review_pair[0]["similarity"] < 0.90

            with store.batch_pool.connection() as conn:
                assert _fetch_superseded_by(conn, id_a) is None
                assert _fetch_superseded_by(conn, id_b) is None
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = ANY(%s)", ([id_a, id_b],))
                conn.commit()

    def test_dry_run_writes_nothing(self):
        store = _pg_only()
        vec = _unit_vector(80)
        with store.batch_pool.connection() as conn:
            cold_id = _insert(
                conn, content=_unique_content("dry-cold"), embedding=vec, heat_base=0.1
            )
            hot_id = _insert(
                conn, content=_unique_content("dry-hot"), embedding=vec, heat_base=0.9
            )
            conn.commit()
        try:
            result = asyncio.run(
                run_near_dup_apply_pass(
                    store, threshold=0.90, apply=False, top_k=10, min_similarity=0.75
                )
            )
            assert result["superseded_total"] >= 1
            with store.batch_pool.connection() as conn:
                assert _fetch_superseded_by(conn, cold_id) is None
                assert _fetch_superseded_by(conn, hot_id) is None
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)", ([cold_id, hot_id],)
                )
                conn.commit()

    def test_transitive_component_of_three_elects_one_survivor(self):
        store = _pg_only()
        vec = _unit_vector(90)
        with store.batch_pool.connection() as conn:
            a_id = _insert(
                conn, content=_unique_content("chain-a"), embedding=vec, heat_base=0.2
            )
            b_id = _insert(
                conn, content=_unique_content("chain-b"), embedding=vec, heat_base=0.9
            )
            c_id = _insert(
                conn, content=_unique_content("chain-c"), embedding=vec, heat_base=0.5
            )
            conn.commit()
        try:
            result = asyncio.run(
                run_near_dup_apply_pass(
                    store, threshold=0.90, apply=True, top_k=10, min_similarity=0.75
                )
            )
            group = next(
                (j for j in result["journal"] if j["survivor_id"] == b_id), None
            )
            assert group is not None
            assert set(group["superseded_ids"]) == {a_id, c_id}
            assert group["component_size"] == 3
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)", ([a_id, b_id, c_id],)
                )
                conn.commit()
