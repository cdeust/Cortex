"""run_near_dup_apply_pass never supersedes a memory through a chain.

Points on an arc of the (e_i, e_j) plane, 23 degrees apart: neighbours have
cosine cos(23) = 0.921 (>= the 0.90 threshold), points two steps apart have
cos(46) = 0.695 (below the 0.75 scan floor, not even a candidate pair).
Live PG (throwaway test database via conftest); skipped on SQLite.

source: ADR-0370
"""

from __future__ import annotations

import asyncio
import math
import uuid

import pytest

from mcp_server.handlers.consolidation.near_dup_calibration_pass import (
    run_near_dup_apply_pass,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from tests_py._pg_hnsw import empty_memories_index

_DIM = 384  # source: memory_config EMBEDDING_DIM (all-MiniLM-L6-v2)
_STEP = math.radians(23)  # source: cos(23 deg) = 0.921 >= 0.90 > 0.75 > cos(46 deg)
_THRESHOLD = 0.90  # source: ADR-0370 (threshold measured on the owner store)


def _store():
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    if not hasattr(store, "batch_pool"):
        pytest.skip("run_near_dup_apply_pass is PostgreSQL-only")
    return store


@pytest.fixture(autouse=True)
def _empty_hnsw_index():
    """Assertions read the HNSW top-K: start from an empty index."""
    store = _store()
    with store.batch_pool.connection() as conn:
        empty_memories_index(conn)


def _arc_vector(axis: int, step: int) -> str:
    values = ["0"] * _DIM
    values[axis] = repr(math.cos(step * _STEP))
    values[axis + 1] = repr(math.sin(step * _STEP))
    return "[" + ",".join(values) + "]"


def _insert_arc(axis: int, heats: list[float]) -> list[int]:
    """One row per point of the arc, ``heats[k]`` for the k-th point."""
    ids = []
    with _store().batch_pool.connection() as conn:
        for step, heat in enumerate(heats):
            row = conn.execute(
                "INSERT INTO memories (content, embedding, tags, source,"
                " heat_base, no_decay) VALUES (%s, %s::vector, '[]'::jsonb,"
                " 'test', %s, TRUE) RETURNING id",
                (f"near-dup chain {uuid.uuid4().hex}", _arc_vector(axis, step), heat),
            ).fetchone()
            ids.append(row["id"])
        conn.commit()
    return ids


def _apply(apply: bool) -> dict:
    result = asyncio.run(
        run_near_dup_apply_pass(
            _store(), threshold=_THRESHOLD, apply=apply, top_k=10, min_similarity=0.75
        )
    )
    assert result["status"] == "ok"
    return result


def _superseded_by(ids: list[int]) -> dict[int, int | None]:
    with _store().batch_pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, superseded_by_id FROM memories WHERE id = ANY(%s)", (ids,)
        ).fetchall()
    return {r["id"]: r["superseded_by_id"] for r in rows}


def _groups(result: dict) -> set[tuple[int, frozenset[int]]]:
    return {
        (j["survivor_id"], frozenset(j["superseded_ids"])) for j in result["journal"]
    }


def test_chain_end_is_not_superseded_into_the_far_end():
    """A~B~C, A hottest: B joins A, C (sim 0.695 to A) stays as it is."""
    a, b, c = _insert_arc(100, [0.9, 0.5, 0.2])
    result = _apply(apply=True)
    assert _groups(result) == {(a, frozenset({b}))}
    assert _superseded_by([a, b, c]) == {a: None, b: a, c: None}
    assert result["unmerged_total"] == 1
    # Review of #756: the ids left unmerged are reported, not only counted.
    assert result["unmerged_ids"] == [c]


def test_chain_symmetric_case_far_end_hottest():
    """A~B~C, C hottest: B joins C, A stays as it is."""
    a, b, c = _insert_arc(110, [0.2, 0.5, 0.9])
    result = _apply(apply=True)
    assert _groups(result) == {(c, frozenset({b}))}
    assert _superseded_by([a, b, c]) == {a: None, b: c, c: None}


def test_chain_hub_hottest_collapses_its_two_true_duplicates():
    """A~B~C, B hottest: A and C both duplicate B, both join it."""
    a, b, c = _insert_arc(120, [0.2, 0.9, 0.5])
    result = _apply(apply=True)
    assert _groups(result) == {(b, frozenset({a, c}))}
    assert _superseded_by([a, b, c]) == {a: b, b: None, c: b}


def test_rest_of_a_chain_forms_its_own_group():
    """A~B~C~D, A hottest then D: {A, B} and {D, C}, never C or D into A."""
    a, b, c, d = _insert_arc(130, [0.9, 0.1, 0.2, 0.8])
    result = _apply(apply=True)
    assert _groups(result) == {(a, frozenset({b})), (d, frozenset({c}))}
    assert _superseded_by([a, b, c, d]) == {a: None, b: a, c: d, d: None}


def test_every_superseded_member_duplicates_its_survivor():
    """Direct similarity, measured in SQL, of every journal (member,
    survivor) pair on a long chain is >= the threshold."""
    _insert_arc(140, [0.9, 0.3, 0.6, 0.1, 0.8, 0.4, 0.7])
    result = _apply(apply=False)
    pairs = [
        (m, j["survivor_id"]) for j in result["journal"] for m in j["superseded_ids"]
    ]
    assert pairs
    with _store().batch_pool.connection() as conn:
        for member, survivor in pairs:
            row = conn.execute(
                "SELECT 1 - (a.embedding <=> b.embedding) AS sim FROM memories a,"
                " memories b WHERE a.id = %s AND b.id = %s",
                (member, survivor),
            ).fetchone()
            assert row["sim"] >= _THRESHOLD


def test_two_dry_runs_give_the_same_journal():
    _insert_arc(150, [0.9, 0.3, 0.6, 0.1, 0.8, 0.4, 0.7])
    _insert_arc(160, [0.5, 0.5, 0.5])
    first, second = _apply(apply=False), _apply(apply=False)
    assert first["journal"]
    assert first["journal"] == second["journal"]
