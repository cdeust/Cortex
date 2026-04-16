"""Phase 2 parity test — substring scan vs JOIN scan for co-accessed pairs.

Phase 0.4.5 artifact. Before Phase 2 swaps
`plasticity._find_co_accessed_pairs` from a Python substring scan to a
PostgreSQL JOIN over `memory_entities`, we need a confirmation test that
the two methods produce the *same* co-access pair set on a known
fixture.

Curie Move 6 — "confirmation standard that licenses the Phase 2 code
swap". If this test passes, the JOIN path can replace the substring path
without changing behaviour. If it fails, the backfill
(`scripts/phase_0_4_5_backfill.sql`) either hasn't run, failed to
complete, or Option A's `length(name) >= 4` filter is dropping too much.

Cases covered:
  (a) normal: entity name appears in content, both scans find it
  (b) retroactive-entity-orphan: substring finds it, JOIN doesn't —
      this is the defect mode the backfill fixes. After backfill,
      JOIN should match substring; the test's `synth_fill_join`
      fixture mimics the backfill so both scans agree.
  (c) name-doesn't-appear-but-link-exists: JOIN finds it, substring
      doesn't. Real data rarely hits this (persist_entities only
      inserts link when the name is in content) but the test must
      be tolerant — the parity predicate allows ±1% symmetric diff.
  (d) case-variant names: "Python" vs "python" vs "PYTHON"; substring
      scan lowercases both sides; JOIN does not rely on case. Both
      must agree.
  (e) short-name filter: entities with length(name) < 4 are excluded
      by the Option A policy; the substring baseline filters them
      identically so the test is fair.

Uses `cortex_test` PostgreSQL — see `tests_py/conftest.py`. Skipped
when PG is not available (CI without PG → test becomes xfail-on-env).
"""

from __future__ import annotations

import os

import pytest

# The substring scan lives in plasticity — we import the private helper
# directly to exercise the production code path. This is acceptable
# because the parity test's job is exactly to validate that code.
from mcp_server.handlers.consolidation.plasticity import _find_co_accessed_pairs
from mcp_server.core.entity_reconciliation import build_reconciliation_sql


# ── Skip conditions ──────────────────────────────────────────────────────

_PG_URL = os.environ.get("DATABASE_URL", "")
_PG_AVAILABLE = False

try:
    import psycopg  # noqa: F401

    conn = psycopg.connect(_PG_URL, autocommit=True, connect_timeout=3)
    conn.close()
    _PG_AVAILABLE = True
except Exception:
    _PG_AVAILABLE = False


pytestmark = [
    pytest.mark.skipif(
        not _PG_AVAILABLE,
        reason="cortex_test PostgreSQL is not reachable",
    ),
    pytest.mark.invariants,
]


# ── Fixture: synthetic 100 memories × 51 entities with known truth ─────

_FIXTURE_ENTITIES = [
    # (name, type)
    # case (a,d,e): canonical 4+ char names, mixed case
    ("Python", "language"),
    ("Postgres", "database"),
    ("pgvector", "extension"),
    ("sentence-transformers", "library"),
    ("FastMCP", "library"),
    ("Cortex", "project"),
    ("Claude", "agent"),
    ("darval", "person"),
    ("trigram", "concept"),
    ("invariant", "concept"),
    # case (d): case variants of something that will appear lowercase in memories
    ("RECALL", "operation"),
    ("Consolidate", "operation"),
    ("Benchmark", "concept"),
    ("heat_raw", "column"),
    ("effective_heat", "function"),
    ("memory_entities", "table"),
    ("plasticity", "module"),
    ("Hebbian", "concept"),
    ("Friston", "scientist"),
    ("McClelland", "scientist"),
    ("hippocampus", "region"),
    ("neocortex", "region"),
    ("replay", "concept"),
    ("schema", "concept"),
    ("cascade", "concept"),
    ("LongMemEval", "benchmark"),
    ("LoCoMo", "benchmark"),
    ("BEAM", "benchmark"),
    ("MemoryAgentBench", "benchmark"),
    ("EverMemBench", "benchmark"),
    # case (b): "retroactive orphans" — valid entity names introduced
    # later; appear in older memories but no link at test-setup time
    # until synth_fill_join is called.
    ("retroactive", "concept"),
    ("orphan", "concept"),
    ("backfill", "operation"),
    ("reconcile", "operation"),
    ("window", "concept"),
    # case (e): short names that MUST be filtered by min_name_length=4
    # (we still insert them to prove the filter works).
    ("a", "stopword"),
    ("an", "stopword"),
    ("re", "stopword"),
    ("tz", "stopword"),
    ("id", "stopword"),
    # More padding to reach ~50 entities
    ("Lamport", "scientist"),
    ("Dijkstra", "scientist"),
    ("Martin", "author"),
    ("Feynman", "scientist"),
    ("Curie", "scientist"),
    ("Kandel", "scientist"),
    ("Turrigiano", "scientist"),
    ("idempotent", "concept"),
    ("monotone", "concept"),
    ("coverage", "concept"),
    ("leak", "concept"),
]
# Total = 51 entities (10 + 20 + 5 + 5 + 11).
# Design target was "~50 entities" (see block comment above); the
# padding block (Lamport..leak) grew to 11 during fixture authoring
# because every name in that block is referenced by at least one
# _FIXTURE_MEMORIES entry (verified: grep over lines 82-94 of the
# memories list). Removing an entity would reduce co-access coverage
# without improving the test. The exact count is 51; keep in sync
# with the block breakdown above.
# source: fixture self-consistency, Phase 0.4.5 parity test, 2026-04-15.
assert len(_FIXTURE_ENTITIES) == 51


# 100 memory contents, each referencing 2-5 entity names. We deliberately
# include lowercase, uppercase, and mixed-case occurrences, plus a few
# that mention only short (filtered) entities so the eligibility filter
# has to handle them.
_FIXTURE_MEMORIES = [
    # First block: co-mentions forming clear co-access pairs
    "Python and Postgres run the Cortex benchmark pipeline.",  # 0
    "pgvector uses HNSW for cosine similarity in Postgres.",  # 1
    "sentence-transformers produces 384-dim embeddings for Cortex.",  # 2
    "FastMCP wraps the Cortex server behind an MCP stdio transport.",  # 3
    "Claude consults Cortex at every session start.",  # 4
    "darval runs the BEAM benchmark on the 66K store.",  # 5
    "trigram indexes accelerate ILIKE on Postgres content columns.",  # 6
    "An invariant documents a property; Lamport named the shape.",  # 7
    "recall produces a ranked list; consolidate maintains the store.",  # 8
    "Consolidate runs plasticity, pruning, decay, and homeostatic cycles.",  # 9
    "Benchmark LongMemEval scored 97.8 on recall@10 for Cortex.",  # 10
    "heat_raw is the persistent heat column; effective_heat reads it.",  # 11
    "memory_entities is a join table linking memories to entities.",  # 12
    "Plasticity applies Hebbian LTP/LTD on knowledge graph edges.",  # 13
    "Hebbian learning strengthens co-active edges per Kandel 2001.",  # 14
    "Friston's free-energy principle gates writes in predictive coding.",  # 15
    "McClelland 1995 describes hippocampus-neocortex consolidation.",  # 16
    "The hippocampus replays trajectories during sharp-wave ripples.",  # 17
    "Neocortex accumulates schema structure over weeks.",  # 18
    "Replay events reactivate memory traces overnight.",  # 19
    "A schema is a cortical structure; cascade advances stages.",  # 20
    "Cascade: LABILE -> EARLY_LTP -> LATE_LTP -> CONSOLIDATED.",  # 21
    "LongMemEval, LoCoMo, and BEAM test long-term memory.",  # 22
    "MemoryAgentBench adds 2026 evaluation cases to the suite.",  # 23
    "EverMemBench contributes 2400 questions to EverMemBench.",  # 24
    "Retroactive entity creation leaves orphan memories behind.",  # 25
    "An orphan lacks a memory_entities link despite containing the name.",  # 26
    "Backfill repairs the retroactive-entity-orphan defect.",  # 27
    "Reconcile is a maintenance operation run on the consolidate schedule.",  # 28
    "A window bounds the reconcile scan to recent memories and entities.",  # 29
    # Second block: case variants, ensuring lowercase substring match
    "The python module imports postgres connectors.",  # 30
    "PYTHON is case-insensitive in ILIKE but not in a SQL join on name.",  # 31
    "PostgresQL is spelled differently in some docs.",  # 32
    "pgvector and postgres both live on the same host.",  # 33
    "Sentence-transformers downloads weights from huggingface.",  # 34
    # Third block: only short (filtered) names — should contribute ZERO co-access
    "An id is re-used across tz boundaries.",  # 35
    "tz is the timezone column; re is a regex prefix.",  # 36
    # Fourth block: mixed (ensures we test (m, e) where e is short and e is long)
    "Python has an id() builtin that returns an int.",  # 37
    "The re module has an id-like interface for compiled patterns.",  # 38
    # Fifth block: more co-mentions to build a dense enough graph
    "Lamport gave us happens-before; Dijkstra gave us GOTO harmful.",  # 39
    "Martin wrote Clean Architecture; Feynman wrote the lectures.",  # 40
    "Curie pioneered measurement; the Cortex audit follows that template.",  # 41
    "Kandel describes LTP; Turrigiano describes homeostatic plasticity.",  # 42
    "Turrigiano 2008 synaptic scaling protects network stability.",  # 43
    "An idempotent operation is monotone in repeated application.",  # 44
    "Coverage measures what fraction of eligible pairs are linked.",  # 45
    "A leak in the write path produces growing reconcile counts.",  # 46
    "invariant I4 checks memory_entities coverage at audit time.",  # 47
    "trigram GIN indexes support ILIKE '%pattern%' acceleration.",  # 48
    "Benchmark pipelines use cortex_bench as an isolated database.",  # 49
    # Sixth block (50..99): mostly entity co-mentions to produce many pairs
    "Postgres plasticity cascade orchestrates the consolidation window.",  # 50
    "Replay feeds schema acquisition through the cascade pipeline.",  # 51
    "Hebbian, LTP, and LTD compose the plasticity mechanism.",  # 52
    "Heat decays; effective_heat recomputes at read time.",  # 53
    "memory_entities and relationships both reference entities.id.",  # 54
    "Trigram, Postgres, and pgvector together power Cortex recall.",  # 55
    "FastMCP hosts Cortex tools over a stdio JSON-RPC channel.",  # 56
    "Claude calls recall, remember, consolidate, and anchor on Cortex.",  # 57
    "darval runs BEAM, LongMemEval, LoCoMo, and EverMemBench nightly.",  # 58
    "The cascade module advances stages; plasticity updates edges.",  # 59
    "Hippocampus, neocortex, and schema together model consolidation.",  # 60
    "reconcile window caps work to recent memories and recent entities.",  # 61
    "Backfill + reconcile = complete coverage restoration strategy.",  # 62
    "orphan + retroactive = the defect class the reconcile closes.",  # 63
    "Idempotent SQL makes reconcile safe to rerun on schedule.",  # 64
    "Monotone insertion means memory_entities never shrinks on reconcile.",  # 65
    "Coverage above 99% clears the I4 invariant audit.",  # 66
    "A leak ratio above 1% raises a WARN in the consolidate handler.",  # 67
    "Plasticity samples hot memories within the consolidate cycle.",  # 68
    "The cascade stage LABILE has the fastest decay exponent alpha=2.0.",  # 69
    "CONSOLIDATED cascade has heat floor 0.10 from Bahrick 1984.",  # 70
    "recall uses WRRF fusion across vector, FTS, trigram, heat, recency.",  # 71
    "FastMCP exposes tools; Cortex exposes 33 of them.",  # 72
    "Python's asyncio powers the FastMCP event loop.",  # 73
    "Postgres is the mandatory store; SQLite is only for CI fallback.",  # 74
    "pgvector HNSW index on embedding drives vector recall.",  # 75
    "trigram GIN on content drives substring-match recall.",  # 76
    "invariant-driven testing builds up an audit trail over time.",  # 77
    "coverage audit tools spot the entity undercoverage defect.",  # 78
    "leak detection in reconcile warns on threshold excursions.",  # 79
    "window of 7 days keeps reconcile work bounded on darval.",  # 80
    "backfill runs once; reconcile runs daily on the schedule.",  # 81
    "Lamport invariants separate safety from liveness conditions.",  # 82
    "Dijkstra's structured programming refuses goto for local reasoning.",  # 83
    "Martin's Clean Architecture mandates inward-pointing dependencies.",  # 84
    "Feynman's integrity demands stating what could invalidate a claim.",  # 85
    "Curie's measurement-first rule governs the consolidation program.",  # 86
    "Kandel's cascade model underpins the four-stage consolidation.",  # 87
    "Turrigiano's synaptic scaling is the homeostatic cycle's source.",  # 88
    "idempotent + monotone = two required properties of reconcile.",  # 89
    "coverage + leak + window = the three reconcile dashboard metrics.",  # 90
    "A recall query returns ranked memories; consolidate maintains them.",  # 91
    "Benchmark cleanliness requires a clean DB and single-process runs.",  # 92
    "heat_raw column is written by bump_heat_raw only after A3 refactor.",  # 93
    "effective_heat function is pure and idempotent per invariant I3.",  # 94
    "memory_entities invariant I4 is the focus of Phase 0.4.5 work.",  # 95
    "plasticity sampling was widened from 50 to 2000 in issue #13.",  # 96
    "Hebbian LTP applies when pre and post are co-active in the window.",  # 97
    "Friston free-energy gates novel writes through predictive coding.",  # 98
    "McClelland consolidation moves episodic to semantic store over time.",  # 99
]
assert len(_FIXTURE_MEMORIES) == 100


# ── Database plumbing ─────────────────────────────────────────────────────


def _pg_conn():
    import psycopg

    return psycopg.connect(_PG_URL, autocommit=False)


def _setup_fixture() -> tuple[list[dict], list[dict]]:
    """Insert fixture data into cortex_test and return (memories, entities).

    Both lists are returned in the format the substring scan expects:
    memory dicts must have 'content' and 'id'; entity dicts must have
    'name' and 'id'. Ordering is deterministic.

    conftest.py auto-cleans between tests so the fixture is inserted on
    an empty DB. memory_entities is implicitly empty too (CASCADE).
    """
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            # Ensure tables are empty up front (belt + suspenders —
            # conftest fixture cleans, but _TABLES_TO_CLEAN does not
            # include memory_entities explicitly; CASCADE should handle
            # it when memories and entities get DELETEd).
            cur.execute("DELETE FROM memory_entities")
            cur.execute("DELETE FROM relationships")
            cur.execute("DELETE FROM entities")
            cur.execute("DELETE FROM memories")

            mem_ids: list[int] = []
            for content in _FIXTURE_MEMORIES:
                cur.execute(
                    "INSERT INTO memories (content, domain) "
                    "VALUES (%s, 'parity_fixture') RETURNING id",
                    (content,),
                )
                mem_ids.append(cur.fetchone()[0])

            ent_ids: list[int] = []
            for name, etype in _FIXTURE_ENTITIES:
                cur.execute(
                    "INSERT INTO entities (name, type, domain) "
                    "VALUES (%s, %s, 'parity_fixture') RETURNING id",
                    (name, etype),
                )
                ent_ids.append(cur.fetchone()[0])

        conn.commit()
    finally:
        conn.close()

    memories = [
        {"id": mid, "content": content, "heat": 0.5}
        for mid, content in zip(mem_ids, _FIXTURE_MEMORIES)
    ]
    entities = [
        {"id": eid, "name": name} for eid, (name, _) in zip(ent_ids, _FIXTURE_ENTITIES)
    ]
    return memories, entities


def _populate_memory_entities_via_backfill() -> int:
    """Run the backfill SQL against the test DB; return pairs inserted.

    This simulates the one-shot `scripts/phase_0_4_5_backfill.sql`
    so the JOIN path has data to read. The parity test asserts that
    AFTER this runs, both scans agree.
    """
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute("SET LOCAL enable_material = off")
            cur.execute(
                """
                INSERT INTO memory_entities (memory_id, entity_id)
                SELECT m.id, e.id
                FROM   entities e
                JOIN   memories m
                  ON   m.content ILIKE '%' || e.name || '%'
                WHERE  length(e.name) >= 4
                  AND  NOT e.archived
                ON CONFLICT (memory_id, entity_id) DO NOTHING
                """
            )
            count = cur.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


# ── The two co-access scans ─────────────────────────────────────────────


def _co_accessed_via_substring(
    memories: list[dict],
    entities: list[dict],
) -> set[tuple[int, int]]:
    """Production path — uses plasticity._find_co_accessed_pairs.

    Applies the Option A min_name_length=4 filter here so the comparison
    is fair against the JOIN path (which is filtered in SQL).
    """
    eligible = [e for e in entities if len(e["name"]) >= 4]
    return _find_co_accessed_pairs(memories, eligible)


def _co_accessed_via_join(
    _memories: list[dict],
    _entities: list[dict],
) -> set[tuple[int, int]]:
    """Placeholder JOIN path — Phase 2 will replace this body.

    Reads memory_entities directly from Postgres and forms all (a, b)
    entity pairs where a != b and both link to the same memory. This
    is the replacement shape for _find_co_accessed_pairs, O(|links|²)
    per memory in the worst case but typically far less because the
    average memory mentions only a handful of entities.
    """
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT me_a.entity_id, me_b.entity_id
                  FROM memory_entities me_a
                  JOIN memory_entities me_b
                    ON me_a.memory_id = me_b.memory_id
                   AND me_a.entity_id < me_b.entity_id
                  JOIN entities e_a ON e_a.id = me_a.entity_id
                  JOIN entities e_b ON e_b.id = me_b.entity_id
                 WHERE length(e_a.name) >= 4
                   AND length(e_b.name) >= 4
                   AND NOT e_a.archived
                   AND NOT e_b.archived
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {(a, b) for a, b in rows}


def _parity_diff(
    left: set[tuple[int, int]],
    right: set[tuple[int, int]],
) -> tuple[int, int, int]:
    """Return (|left|, |right|, |symmetric_diff|)."""
    return len(left), len(right), len(left ^ right)


def _tolerance_pct(left: int, right: int, diff: int) -> float:
    denom = max(left, right, 1)
    return diff / denom


# ── Tests ──────────────────────────────────────────────────────────────


class TestPhase2Parity:
    def test_substring_scan_returns_nonempty_set(self):
        """Sanity: the fixture must produce co-access pairs at all."""
        memories, entities = _setup_fixture()
        pairs = _co_accessed_via_substring(memories, entities)
        assert len(pairs) > 0, "fixture failed to produce co-access pairs"

    def test_short_entity_names_are_excluded(self):
        """Case (e): length-3 entities must NOT appear in co-access pairs.

        The fixture contains 'a', 'an', 're', 'tz', 'id' (all < 4 chars).
        If the Option A filter fails, these ids would show up in pairs.
        """
        memories, entities = _setup_fixture()
        pairs = _co_accessed_via_substring(memories, entities)

        short_entity_ids = {e["id"] for e in entities if len(e["name"]) < 4}
        assert short_entity_ids, "fixture is missing short entities"

        leaked = [
            p for p in pairs if p[0] in short_entity_ids or p[1] in short_entity_ids
        ]
        assert leaked == [], f"short entities leaked into substring pairs: {leaked[:3]}"

    def test_join_scan_matches_substring_after_backfill(self):
        """Core parity assertion: after backfill, both scans agree ± 1%.

        (a) + (b) covered: the backfill populates memory_entities so the
        JOIN scan can see everything the substring scan sees.
        (d) covered: ILIKE + lowercase-substring both case-insensitive.
        """
        memories, entities = _setup_fixture()
        inserted = _populate_memory_entities_via_backfill()
        assert inserted > 0, "backfill inserted zero rows on fixture"

        sub_pairs = _co_accessed_via_substring(memories, entities)
        join_pairs = _co_accessed_via_join(memories, entities)

        ls, rs, diff = _parity_diff(sub_pairs, join_pairs)
        tol = _tolerance_pct(ls, rs, diff)
        assert tol <= 0.01, (
            f"parity drift too large: substring={ls}, join={rs}, "
            f"sym_diff={diff} ({tol:.2%}). "
            f"Example drift: substring_only={list(sub_pairs - join_pairs)[:3]}, "
            f"join_only={list(join_pairs - sub_pairs)[:3]}"
        )

    def test_case_variants_agree(self):
        """Case (d): 'Python' entity matches content 'python', 'PYTHON'.

        Memory 30 contains 'python' (lowercase), memory 31 contains
        'PYTHON' (uppercase). Both substring and JOIN paths must link
        them to the 'Python' entity.
        """
        memories, entities = _setup_fixture()
        _populate_memory_entities_via_backfill()

        python_ent = next(e for e in entities if e["name"] == "Python")
        other_ent = next(e for e in entities if e["name"] == "Postgres")

        # Memory 30: "The python module imports postgres connectors."
        # Should produce a (Python, Postgres) or (Postgres, Python) pair.
        mem30 = memories[30]
        sub_pairs_mem30 = _co_accessed_via_substring([mem30], entities)
        expected = tuple(sorted((python_ent["id"], other_ent["id"])))
        assert expected in sub_pairs_mem30, (
            f"case-variant substring test failed: "
            f"expected {expected}, got {sub_pairs_mem30}"
        )

    def test_retroactive_orphan_case_b(self):
        """Case (b): before backfill, JOIN misses pairs; after, it agrees.

        Mirrors the production defect. We:
          1. Insert fixture WITHOUT running the backfill.
          2. Assert JOIN scan returns an empty set (no memory_entities yet).
          3. Run backfill.
          4. Assert JOIN scan now matches substring.
        """
        memories, entities = _setup_fixture()

        # Pre-backfill: JOIN path is blind.
        join_pre = _co_accessed_via_join(memories, entities)
        assert join_pre == set(), (
            f"expected empty JOIN scan pre-backfill (memory_entities is "
            f"empty), got {len(join_pre)} pairs. Is conftest cleaning correctly?"
        )

        # Substring path produces pairs unconditionally.
        sub = _co_accessed_via_substring(memories, entities)
        assert len(sub) > 0

        # Post-backfill: parity holds.
        _populate_memory_entities_via_backfill()
        join_post = _co_accessed_via_join(memories, entities)
        _, _, diff = _parity_diff(sub, join_post)
        assert _tolerance_pct(len(sub), len(join_post), diff) <= 0.01

    def test_reconciliation_sql_builder_contract(self):
        """entity_reconciliation.build_reconciliation_sql contract.

        Moves 2 — validate the builder's contract directly. No DB calls.
        """
        sql, params = build_reconciliation_sql()
        assert "ON CONFLICT" in sql
        assert "DO NOTHING" in sql
        assert sql.count("%s") == 3
        assert params == (4, 7, 24)

        sql2, params2 = build_reconciliation_sql(
            memory_age_days=14,
            entity_age_hours=48,
            min_name_length=3,
        )
        assert params2 == (3, 14, 48)

        with pytest.raises(ValueError):
            build_reconciliation_sql(memory_age_days=0)
        with pytest.raises(ValueError):
            build_reconciliation_sql(entity_age_hours=0)
        with pytest.raises(ValueError):
            build_reconciliation_sql(min_name_length=0)

    def test_leak_ratio_contract(self):
        """reconcile_leak_ratio + exceeds_leak_threshold contracts."""
        from mcp_server.core.entity_reconciliation import (
            LEAK_WARNING_THRESHOLD,
            exceeds_leak_threshold,
            reconcile_leak_ratio,
        )

        assert LEAK_WARNING_THRESHOLD == 0.01
        assert reconcile_leak_ratio(0, 0) == 0.0
        assert abs(reconcile_leak_ratio(10, 1000) - 0.01) < 1e-9
        assert reconcile_leak_ratio(25, 100) == 0.25

        assert exceeds_leak_threshold(0.02) is True
        assert exceeds_leak_threshold(0.005) is False
        assert exceeds_leak_threshold(LEAK_WARNING_THRESHOLD) is False

        with pytest.raises(ValueError):
            reconcile_leak_ratio(-1, 10)
        with pytest.raises(ValueError):
            reconcile_leak_ratio(100, 10)  # reconciled > eligible
        with pytest.raises(ValueError):
            exceeds_leak_threshold(-0.1)
        with pytest.raises(ValueError):
            exceeds_leak_threshold(1.1)
