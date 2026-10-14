"""Read-only SQL shape guards complement the live equivalence and plan gates."""

from __future__ import annotations

import re

from benchmarks.pg_recall_plans.sql import reference_sql
from mcp_server.infrastructure.pg_schema import INDEXES_DDL, RECALL_MEMORIES_LAZY_FN


def compact(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def test_signature_return_shape_and_fusion_unchanged():
    before = reference_sql().replace("recall_memories_reference", "recall_memories")
    after = RECALL_MEMORIES_LAZY_FN
    signature = "CREATE OR REPLACE FUNCTION recall_memories("
    assert compact(before.split(signature)[1].split("AS $$")[0]) == compact(
        after.split(signature)[1].split("AS $$")[0]
    )
    # The frozen reference has no tie-break; ADR-1106 appends one to the final
    # ORDER BY, so the fusion is compared up to it and the order separately.
    final_order = "ORDER BY (c.superseded_by_id IS NOT NULL)"
    assert compact(before.split("vec_max  AS")[1].split(final_order)[0]) == compact(
        after.split("vec_max  AS")[1].split(final_order)[0]
    )
    assert compact(after.split(final_order)[1].split("$$ LANGUAGE")[0]) == (
        ", tw.final_score DESC, c.created_at DESC, tw.id DESC "
        "LIMIT p_max_results * 3; END;"
    )


def test_every_pool_breaks_exact_ties_newest_first():
    """ADR-1106: no LIMIT in recall_memories() cuts ties in heap order."""
    function = RECALL_MEMORIES_LAZY_FN
    for pool in ("vec", "fts", "ngram", "hot", "recency"):
        query = compact(function.split(f"    {pool} AS (")[1].split("    ),")[0])
        assert query.endswith("c.created_at DESC, c.id DESC LIMIT v_pool"), pool


def test_common_filters_inline_and_union_materializes_only_bounded_ids():
    function = RECALL_MEMORIES_LAZY_FN
    assert "eligible AS NOT MATERIALIZED" in function
    eligible = function.split("eligible AS NOT MATERIALIZED (")[1].split("),")[0]
    for gate in (
        "FROM current_memories",
        "m.heat_base >= v_min_heat_base",
        "NOT m.is_stale",
        "m.domain = p_domain",
        "p_include_globals",
        "m.is_global = TRUE",
        "m.directory_context = p_directory",
    ):
        assert gate in eligible
    bounded = function.split("candidates AS MATERIALIZED (")[1].split("),")[0]
    assert all(
        f"SELECT id FROM {pool}" in bounded
        for pool in ("vec", "fts", "ngram", "hot", "recency")
    )
    assert function.count("LIMIT v_pool") == 5
    assert "v_pool   INT := p_max_results * 10" in function


def test_each_pool_filters_exact_heat_before_limit_and_exposes_index_operator():
    function = RECALL_MEMORIES_LAZY_FN
    for pool in ("vec", "fts", "ngram", "hot", "recency"):
        query = function.split(f"    {pool} AS (")[1].split("    ),")[0]
        assert "FROM eligible c" in query
        assert query.index(
            "effective_heat(c, NOW(), v_factor) >= p_min_heat"
        ) < query.index("LIMIT v_pool")
    assert "ORDER BY c.embedding <=> p_query_emb" in function
    assert "c.content_tsv @@ v_tsq" in function
    assert "c.content % p_query_text" in function
    assert "similarity(c.content, p_query_text) > 0.1" in function
    assert "SET pg_trgm.similarity_threshold = '0.1'" in function
    assert "ORDER BY effective_heat(c, NOW(), v_factor) DESC" in function


def test_partial_indexes_match_nullable_source_and_current_predicates():
    for name, key in (("heat_base", "heat_base"), ("created_at", "created_at DESC")):
        index = INDEXES_DDL.split(f"idx_memories_curated_{name}")[1].split(";")[0]
        assert f"ON memories ({key})" in index
        assert "source <> 'post_tool_capture' AND NOT is_stale" in index
        assert "superseded_by_id IS NULL" in index
        assert "NOW()" not in index
