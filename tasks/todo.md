# PostgreSQL + pgvector Migration

## Problem

Two parallel retrieval systems that share zero code:

1. **Production** (`mcp_server/`): 9-signal WRRF -> 3-tier dispatch -> FlashRank, backed by SQLite
2. **Benchmarks** (`benchmarks/`): 3 custom retrievers (`InMemoryRetriever`, `LoCoMoRetriever`, `BEAMRetriever`), each reimplementing scoring, fusion, reranking from scratch

Improving benchmarks doesn't improve the product. Improving the product doesn't improve benchmarks. The benchmark scores measure throwaway code, not the system users get.

## Solution

**PostgreSQL + pgvector** as the single storage + retrieval engine. **Mandatory.** No SQLite. No in-memory hacks.

Core retrieval logic lives in **PL/pgSQL stored procedures** -- server-side computation. Benchmarks and production call the **exact same functions**.

---

## Implementation Phases

### Phase 1: PostgreSQL Infrastructure -- COMPLETE
- [x] `pg_schema.py` -- DDL, extensions, all tables, HNSW/GIN indexes
- [x] `pg_store.py` -- PgMemoryStore composing 6 mixins (92 methods)
- [x] `pg_store_entities.py` -- Entity CRUD with phraseto_tsquery
- [x] `pg_store_relationships.py` -- Relationship CRUD
- [x] `pg_store_queries.py` -- Filtered reads, time windows, decay
- [x] `pg_store_rules.py` -- Rule CRUD
- [x] `pg_store_stats.py` -- Counts, consolidation, oscillatory state, CLS
- [x] `pg_store_auxiliary.py` -- Prospective, checkpoints, archives, engrams, schemas
- [x] `memory_config.py` -- DATABASE_URL added (mandatory PG)
- [x] PL/pgSQL `recall_memories()` -- 5-signal WRRF fusion server-side
- [x] PL/pgSQL `decay_memories()` -- batch thermodynamic decay
- [x] PL/pgSQL `spread_activation()` -- recursive CTE over entity graph
- [x] `pyproject.toml` -- psycopg[binary], pgvector dependencies
- [x] Integration tested against PostgreSQL 17 + pgvector 0.8.2
- [x] All 3 PL/pgSQL functions verified working

### Phase 2: Wire Handlers -- COMPLETE
- [x] `memory_store.py` -- Compat layer: `MemoryStore(PgMemoryStore)` with legacy constructor
- [x] All 42 importing files work without modification
- [x] Fixed 15 raw `_conn.execute()` calls: `?` -> `%s` placeholders
- [x] Fixed SQLite DDL in `backfill_helpers.py` -> PostgreSQL DDL
- [x] Fixed `is_protected = 1` -> `TRUE` in anchor.py
- [x] Fixed embedding updates in sleep.py to use `_bytes_to_vector()`
- [x] Added `_now_iso()` and `_row_to_dict()` compat methods
- [x] Ruff lint passes on all modified files

### Phase 3: Benchmark Migration
- [ ] `benchmarks/lib/bench_db.py` -- load data -> PG, cleanup after
- [ ] Each benchmark runner -> loads data via bench_db, calls production recall
- [ ] Delete all custom retrievers:
  - `benchmarks/lib/retriever.py`
  - `benchmarks/lib/fusion.py`
  - `benchmarks/locomo/retriever.py`
  - LongMemEval `InMemoryRetriever` (900 lines of dead code)
  - BEAM `BEAMRetriever` + `FactScratchpad`
- [ ] Verify benchmark scores match or improve

### Phase 4: Advanced Server-Side Signals
- [ ] Spreading activation as recursive CTE (already drafted)
- [ ] Hopfield recall via PG function
- [ ] Successor representation via co-access in PG
- [ ] HDC encoding server-side

### Phase 5: Cleanup
- [ ] Delete old SQLite mixin files (10 files):
  - `memory_store_auxiliary.py`
  - `memory_store_entities.py`
  - `memory_store_queries.py`
  - `memory_store_relationships.py`
  - `memory_store_rules.py`
  - `memory_store_schema_init.py`
  - `memory_store_schemas.py`
  - `memory_store_search.py`
  - `memory_store_stats.py`
  - Remove compat layer, make `memory_store.py` a re-export
- [ ] Delete custom benchmark retrievers (5 files)

---

## Environment

```bash
# PostgreSQL 17 + pgvector 0.8.2 + pg_trgm
DATABASE_URL=postgresql://localhost:5432/cortex

# Extensions (installed via brew install pgvector)
# CREATE EXTENSION IF NOT EXISTS vector;
# CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

## Previous Sprint Results (reference)

| Benchmark | Score |
|---|---|
| LongMemEval R@10 | 98.6% |
| LongMemEval MRR | 0.865 |
| LoCoMo R@10 | 96.8% |
| LoCoMo MRR | 0.779 |
| BEAM MRR (retrieval) | 0.275 |
