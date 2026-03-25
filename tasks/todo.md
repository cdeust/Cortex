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

### Phase 3: Benchmark Migration -- COMPLETE
- [x] `benchmarks/lib/bench_db.py` -- BenchmarkDB: load→PG, recall→production, cleanup
- [x] LongMemEval `run_benchmark.py` -- rewritten to use BenchmarkDB (removed InMemoryRetriever, 900→250 lines)
- [x] LoCoMo `run_benchmark.py` -- rewritten to use BenchmarkDB
- [x] BEAM `run_benchmark.py` -- rewritten to use BenchmarkDB (removed BEAMRetriever + FactScratchpad)
- [x] Deleted `benchmarks/locomo/retriever.py` (528 lines)
- [x] Removed LongMemEval InMemoryRetriever (inline, ~800 lines)
- [x] Removed BEAM BEAMRetriever + FactScratchpad (inline, ~150 lines)
- [ ] `benchmarks/lib/retriever.py` + `fusion.py` kept (still used by Tier 2 benchmarks: episodic, memoryagentbench, evermembench)
- [ ] Verify benchmark scores match or improve

### Phase 4: Advanced Server-Side Signals -- COMPLETE
- [x] `spread_activation_memories()` PL/pgSQL — full pipeline: query terms → entity resolution → recursive CTE propagation → FTS memory mapping (replaces 4 Python round trips with 1 server call)
- [x] `get_hot_embeddings()` PL/pgSQL — efficient batch fetch of (id, embedding, heat) for Hopfield (single round trip vs full memory row fetch)
- [x] `get_temporal_co_access()` PL/pgSQL — memory pair proximity within time window for SR graph building (server-side join vs N² Python)
- [x] Wired into `retrieval_signals.py` — SA uses PG-side function, Hopfield uses PG embedding fetch, SR uses PG co-access
- [x] HDC stays client-side (bipolar vector math, no PG equivalent possible)
- [x] Hopfield core math stays client-side (numpy softmax attention)

### Phase 5: Cleanup -- COMPLETE
- [x] Deleted 9 old SQLite mixin files (memory_store_*.py) — zero imports found
- [x] Simplified `memory_store.py` — removed deprecation warning and _row_to_dict shim, kept compat constructor (20+ callers still pass db_path/embedding_dim)
- [x] Deleted `benchmarks/locomo/retriever.py` (Phase 3)
- [x] Removed inline LongMemEval InMemoryRetriever + BEAM BEAMRetriever (Phase 3)
- [ ] `benchmarks/lib/retriever.py` + `fusion.py` kept — Tier 2 benchmarks still depend on them

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
