"""Dup-collapse benchmark for the fuzzy entity deduplicator.

Measures how many near-duplicate *concept* entities the 3-pass MinHash/LSH/
Jaro-Winkler deduplicator (``mcp_server.core.entity_dedup``) collapses that the
exact-name + case-canonical insert policy leaves behind.

READ-ONLY: loads entities via ``get_all_entities`` and runs the pure planner.
It never mutates the store — it reports the remap that a future merge pass would
apply, so the before/after collapse can be reviewed before any FK rewiring.

Usage:
    python3 benchmarks/entity_dedup/run_benchmark.py            # live DB
    python3 benchmarks/entity_dedup/run_benchmark.py --fixture  # no DB needed
    python3 benchmarks/entity_dedup/run_benchmark.py --samples 40
"""

from __future__ import annotations

import argparse
import sys

from mcp_server.core.entity_dedup import FUZZY_ELIGIBLE_TYPES, deduplicate_entities

# Deterministic fixture: real-world spelling/spacing/typo variants that the
# exact-name + case policy misses. Used when no DB is available.
_FIXTURE = [
    {"id": 1, "name": "Embedding Engine", "type": "technology", "mention_count": 3},
    {"id": 2, "name": "EmbeddingEngine", "type": "technology", "mention_count": 9},
    {"id": 3, "name": "embedding-engine", "type": "technology", "mention_count": 1},
    {"id": 4, "name": "PostgreSQL", "type": "technology", "mention_count": 12},
    {"id": 5, "name": "Postgre SQL", "type": "technology", "mention_count": 2},
    {"id": 6, "name": "Vector Store", "type": "technology", "mention_count": 5},
    {"id": 7, "name": "VectorStore", "type": "technology", "mention_count": 8},
    {"id": 8, "name": "Redis", "type": "dependency", "mention_count": 4},
    {"id": 9, "name": "Kafka", "type": "dependency", "mention_count": 1},
    # Should NOT merge: strict suffix-extension and SKU variant.
    {"id": 10, "name": "parseConfigStage", "type": "technology", "mention_count": 1},
    {
        "id": 11,
        "name": "parseConfigStageFile",
        "type": "technology",
        "mention_count": 1,
    },
]


def _load_live(samples: int) -> list[dict]:
    """Load fuzzy-eligible entities from the live store (read-only)."""
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it

    store = PgMemoryStore()
    try:
        ents = store.get_all_entities(min_heat=0.0, include_archived=True)
    finally:
        store.close()
    # The dedup engine only fuzzy-merges text-extracted concepts; report the
    # true eligible population (text_concept + eligible type) and how many
    # AST-extracted code symbols are correctly excluded.
    typed = [e for e in ents if e.get("type") in FUZZY_ELIGIBLE_TYPES]
    eligible = [e for e in typed if e.get("origin", "text_concept") != "ast_symbol"]
    excluded = len(typed) - len(eligible)
    print(f"ast_symbol entities excluded from fuzzy: {excluded}")
    print(f"total entities in store:                 {len(ents)}")
    if samples and len(eligible) > samples:
        # Deterministic slice (sorted by name) so runs are reproducible.
        eligible = sorted(eligible, key=lambda e: str(e.get("name", "")))[:samples]
    return eligible


def _report(entities: list[dict], sample_merges: int) -> None:
    """Run the planner and print before/after collapse metrics."""
    result = deduplicate_entities(entities)
    collapsed = len(result.remap)
    before = len(entities)
    after = len(result.survivors)
    print(f"eligible entities (before):  {before}")
    print(f"survivors (after):           {after}")
    print(f"aliases collapsed:           {collapsed}")
    print(f"matched pairs:               {len(result.merges)}")
    if before:
        print(f"collapse rate:               {collapsed / before:.2%}")

    exact = [m for m in result.merges if m.reason.startswith("exact-norm")]
    fuzzy = [m for m in result.merges if m.reason == "jaro-winkler"]
    print(f"  exact-norm merges:         {len(exact)}")
    print(f"  fuzzy (Jaro-Winkler):      {len(fuzzy)}")

    by_key = {str(e.get("id", e.get("name"))): e for e in entities}
    print(f"\nsample merges (up to {sample_merges}):")
    for m in (fuzzy + exact)[:sample_merges]:
        a = by_key.get(m.key_a, {}).get("name", m.key_a)
        b = by_key.get(m.key_b, {}).get("name", m.key_b)
        print(f"  {a!r:32} ~ {b!r:32} score={m.score:.3f} [{m.reason}]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Entity dedup dup-collapse benchmark")
    parser.add_argument(
        "--fixture", action="store_true", help="Run on the in-file fixture (no DB)"
    )
    parser.add_argument(
        "--samples", type=int, default=0, help="Cap live entities to N (0=all)"
    )
    parser.add_argument(
        "--sample-merges", type=int, default=25, help="How many merges to print"
    )
    args = parser.parse_args()

    if args.fixture:
        print("=== entity dedup dup-collapse (fixture) ===")
        _report(_FIXTURE, args.sample_merges)
        return 0

    print("=== entity dedup dup-collapse (live, read-only) ===")
    try:
        entities = _load_live(args.samples)
    except Exception as exc:  # noqa: BLE001 — benchmark CLI, surface and exit
        print(f"DB unavailable ({type(exc).__name__}: {exc}); try --fixture.")
        return 1
    _report(entities, args.sample_merges)
    return 0


if __name__ == "__main__":
    sys.exit(main())
