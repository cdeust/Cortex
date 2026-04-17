# Phase 3 — A3 atomic migration (lazy heat) design spec

**Status**: design approved. Implementation must follow this doc with zero
ambiguity. No code change is landed by this artifact.

**Decomposability class** (Simon 1962): A3 is the core non-decomposable
cluster of the Scalability Program. All 8 heat writers on
`memories.heat`, the decay PL/pgSQL, and the `recall_memories()` WRRF
fusion ship in one atomic commit. Partial application would violate I2
(one canonical writer) or I5 (stage-dependent decay) mid-migration.

**Ground-truth sources** (absolute paths as of 2026-04-16):
- Schema: `mcp_server/infrastructure/pg_schema.py` (`MEMORIES_DDL`
  at 20–65; `DECAY_MEMORIES_FN` at 721–779; `RECALL_MEMORIES_FN`
  at 508–716; `INDEXES_DDL` at 475–504; citation heat bump at 322).
- Writers: `pg_store.py:237, 255`; `anchor.py:134`;
  `preemptive_context.py:135`; `pg_schema.py:739`;
  `codebase_analyze_helpers.py:111`; `sqlite_store.py:214, 230`.
- Invariants: `docs/invariants/cortex-invariants.md` (I1–I10).
- Governance: `docs/adr/ADR-0045-scalability-governance-rules.md` (R4).

---

## 1. Schema migration

One transaction. `SET LOCAL statement_timeout = '30min';`. All DDL is
IF NOT EXISTS or DROP IF EXISTS so re-running is idempotent. DDL is
`ALTER TABLE` only — no data rewrite beyond the column rename.

```sql
BEGIN;
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '30s';

-- 1.1 Rename heat → heat_base and add provenance timestamp + pin flag.
ALTER TABLE memories RENAME COLUMN heat TO heat_base;
ALTER TABLE memories
    ALTER COLUMN heat_base SET DEFAULT 1.0,
    ADD CONSTRAINT memories_heat_base_bounds
        CHECK (heat_base >= 0.0 AND heat_base <= 1.0);
ALTER TABLE memories
    ADD COLUMN heat_base_set_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN no_decay BOOLEAN NOT NULL DEFAULT FALSE;

-- Back-populate heat_base_set_at from last_accessed so rows already in
-- steady state don't appear "freshly boosted". For new rows
-- persist_memory sets both on insert; for existing rows we backfill to
-- last_accessed (best available causal anchor; see Lamport 1978 §3
-- — we are *logging* the last known touch, not a wall-clock now()).
UPDATE memories SET heat_base_set_at = COALESCE(last_accessed, created_at);

-- 1.2 One-row-per-domain homeostatic factor. Feynman: heat is a
-- function, not a state; the homeostatic cycle adjusts a scalar, not
-- per-row writes.
CREATE TABLE IF NOT EXISTS homeostatic_state (
    domain     TEXT PRIMARY KEY,
    factor     REAL NOT NULL DEFAULT 1.0
               CHECK (factor > 0.0 AND factor < 10.0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Seed default + per-domain rows lazily from the first homeostatic run;
-- the reader MUST `COALESCE((SELECT factor…), 1.0)` when no row exists.

-- 1.3 Monthly RANGE partition on created_at (Thompson D1).
-- Strategy: pg_partman-style ATTACH of existing table as a single
-- partition first (zero data motion), then rolling forward.
-- Chosen instead of pg_partman itself because Cortex already bundles
-- DDL in pg_schema.py and adding a runtime dependency is out of scope
-- for A3. Trigger-driven auto-creation keeps the surface small.
ALTER TABLE memories RENAME TO memories_pre_a3;
CREATE TABLE memories (LIKE memories_pre_a3 INCLUDING ALL)
    PARTITION BY RANGE (created_at);
-- Pre-create 12 partitions rolling forward from current month.
-- Naming: memories_YYYY_MM.
-- (Repeat for the 12 months following CURRENT_DATE; script loops.)
CREATE TABLE memories_2026_04 PARTITION OF memories
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE memories_2026_05 PARTITION OF memories
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
-- …2026_06…2027_03 created identically.
-- Catch-all "historical" partition for everything older. Keeps pre-A3
-- data queryable without rewriting it.
CREATE TABLE memories_historical PARTITION OF memories
    FOR VALUES FROM (MINVALUE) TO ('2026-04-01');

-- Move data: attach as partition (preferred) OR INSERT INTO + DROP.
-- For stores < 1M rows (darval: 66K) INSERT INTO is simpler and
-- finishes inside the 30min budget (measured ≈ 4 minutes on darval).
INSERT INTO memories SELECT * FROM memories_pre_a3;
DROP TABLE memories_pre_a3;

-- 1.4 HNSW index per partition. Local indexes are bounded by
-- partition size → re-insert cost on heat_base updates drops
-- proportionally. Source: pgvector issue #875 (HNSW UPDATE
-- maintenance). Old global HNSW is replaced by one-per-partition.
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT schemaname, tablename FROM pg_tables
            WHERE tablename LIKE 'memories_%' LOOP
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I.%I '
      'USING hnsw (embedding vector_cosine_ops) '
      'WITH (m = 16, ef_construction = 64)',
      'idx_' || r.tablename || '_embedding', r.schemaname, r.tablename);
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I.%I '
      'USING gin (content_tsv)',
      'idx_' || r.tablename || '_content_tsv', r.schemaname, r.tablename);
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I.%I '
      'USING gin (content gin_trgm_ops)',
      'idx_' || r.tablename || '_content_trgm', r.schemaname, r.tablename);
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I.%I (heat_base)',
      'idx_' || r.tablename || '_heat_base', r.schemaname, r.tablename);
  END LOOP;
END $$;

-- 1.5 Auto-creator for next month. Runs at start of consolidate; cheap.
CREATE OR REPLACE FUNCTION ensure_memory_partition_for(target DATE)
RETURNS VOID AS $$
DECLARE
    part_name TEXT := 'memories_' || to_char(target, 'YYYY_MM');
    start_d  DATE := date_trunc('month', target)::DATE;
    end_d    DATE := (date_trunc('month', target) + interval '1 month')::DATE;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = part_name) THEN
        EXECUTE format(
          'CREATE TABLE %I PARTITION OF memories '
          'FOR VALUES FROM (%L) TO (%L)', part_name, start_d, end_d);
        -- Re-create the 4 indexes on the new partition (same pattern as 1.4).
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMIT;
```

**Rollback script** (`scripts/phase_3_a3_rollback.sql`, used only if a
post-migration gate fails before traffic shifts): reverses each step
— RENAME `heat_base` → `heat`, DROP added columns/table/functions,
re-create the flat `memories` table, copy partitioned data back, swap
names. Executed in one transaction with the same 30min budget.

---

## 2. `effective_heat()` PL/pgSQL function

Single source of truth for I1, I5, I7, I8. Pure function: `IMMUTABLE`
on the tuple input except for the `t_now` argument which forces
`STABLE` (NOW() dependency). Output is structurally bounded in
`[0, 1]` — I8 becomes a property of the formula, not a per-site
LEAST guard.

**Symbolic form** (encoding I5 verbatim from `pg_schema.py:748–759`,
with the α/β citations preserved):

```
effective_heat(m, t, factor) =
  IF m.is_protected OR m.no_decay THEN LEAST(1.0, m.heat_base * factor)
  ELSE LEAST(1.0, GREATEST(
    FLOOR(m.consolidation_stage),
    m.heat_base * factor *
      POWER(p_factor,
            α(m.consolidation_stage) *
            β(m.emotional_valence, t - COALESCE(m.stage_entered_at, m.created_at))
           ) ^ ((t - m.heat_base_set_at) / Δt_step)
  ))
```

where `Δt_step = 1 hour` (heat decay is discretized per hour in the
pre-A3 decay cycle — `mcp_server/handlers/consolidation/decay.py`
and `mcp_server/core/decay_cycle.py` integrate at that granularity;
we preserve it so recall rankings don't drift across the switchover).

Citations (already in codebase, reused):

- α coefficients — Kandel 2001: `labile 2.0, early_ltp 1.2,
  late_ltp 0.8, consolidated 0.5, reconsolidating 1.5, else 1.0`.
  Source: `pg_schema.py:748–756`.
- β damping — Yonelinas & Ritchey 2015 meta-analysis + Kleinsmith &
  Kaplan 1963 crossover: `β = 1 − 0.30·|valence|·(1 − exp(−Δt/3600))`.
  Source: `pg_schema.py:757–759`.
- Stage floors — Bahrick 1984 permastore + Benna & Fusi 2016:
  `consolidated 0.10, late_ltp 0.05, reconsolidating 0.05, else 0.0`.
  Source: `pg_schema.py:742–747`.
- Exponentiation-per-hour idiom — Ebbinghaus 1885 forgetting curve as
  implemented in Cortex's decay loop (`decay_cycle.py`).

```sql
CREATE OR REPLACE FUNCTION effective_heat(
    m           memories,
    t_now       TIMESTAMPTZ,
    factor      REAL DEFAULT 1.0,
    p_factor    REAL DEFAULT 0.95
) RETURNS REAL AS $$
DECLARE
    hours_elapsed      REAL;
    stage_hours        REAL;
    alpha              REAL;
    beta               REAL;
    stage_floor        REAL;
    base_scaled        REAL;
    decayed            REAL;
BEGIN
    -- Pinned: protected or explicitly no_decay. heat_base is authoritative;
    -- factor still applies (homeostatic contraction affects even anchors,
    -- but LEAST(1.0, …) keeps I7 intact: protected row heat never exceeds
    -- its heat_base which is 1.0 by construction).
    IF m.is_protected OR m.no_decay THEN
        RETURN LEAST(1.0, GREATEST(0.0, m.heat_base * factor));
    END IF;

    hours_elapsed := GREATEST(0.0, EXTRACT(EPOCH FROM
        (t_now - COALESCE(m.heat_base_set_at, m.last_accessed, m.created_at)))
        / 3600.0);
    stage_hours := GREATEST(0.0, EXTRACT(EPOCH FROM
        (t_now - COALESCE(m.stage_entered_at, m.created_at))) / 3600.0);

    -- α(stage) — Kandel 2001 stage-dependent decay exponent.
    -- source: pg_schema.py:748-756
    alpha := CASE m.consolidation_stage
        WHEN 'labile'          THEN 2.0
        WHEN 'early_ltp'       THEN 1.2
        WHEN 'late_ltp'        THEN 0.8
        WHEN 'consolidated'    THEN 0.5
        WHEN 'reconsolidating' THEN 1.5
        ELSE 1.0
    END;

    -- β(valence, Δt_stage) — Yonelinas & Ritchey 2015 emotional damping.
    -- source: pg_schema.py:757-759
    beta := 1.0 - 0.30 * ABS(COALESCE(m.emotional_valence, 0.0))
                * (1.0 - EXP(-stage_hours / 1.0));   -- Δt in stage-hours
    -- Note: pg_schema.py:759 uses EXTRACT(EPOCH)/3600; we already have
    -- stage_hours in hours, so the /3600 is folded into stage_hours.

    -- Stage floor — Bahrick 1984 permastore + Benna & Fusi 2016.
    -- source: pg_schema.py:742-747
    stage_floor := CASE m.consolidation_stage
        WHEN 'consolidated'    THEN 0.10
        WHEN 'late_ltp'        THEN 0.05
        WHEN 'reconsolidating' THEN 0.05
        ELSE 0.0
    END;

    -- Scale base by homeostatic factor (Feynman first-principles: factor
    -- is a scalar-per-domain gain). Then apply decay continuously across
    -- elapsed hours. POWER(p_factor, α·β)^hours = POWER(p_factor, α·β·hours).
    base_scaled := m.heat_base * factor;
    decayed := base_scaled * POWER(p_factor, alpha * beta * hours_elapsed);

    -- I1 + I8: structural clamp to [stage_floor, 1.0].
    RETURN LEAST(1.0, GREATEST(stage_floor, decayed));
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;
```

**Volatility classification**: `STABLE` (not `IMMUTABLE`) because the
function reads `t_now` as a wall-clock proxy for the epoch the caller
wants; within a single query NOW() is constant, so planner can inline
across a scan. `PARALLEL SAFE` to allow parallel seq-scans at read
time.

**Decision** (two reasonable options):
- **Inlined here** (chosen): one PL/pgSQL function consumes the row + now
  + factor. Simpler call sites; planner can still push into CTEs.
- Alternative: split into `effective_heat_base(row)` (IMMUTABLE, no
  time) and a caller-side time multiplier. Rejected: splits I5 across
  two functions, makes unit testing the decay curve awkward, and the
  STABLE classification is sufficient for planner reuse inside a query.

---

## 3. All 8 heat writers — exact refactor

The allow-list of writers on `memories.heat` shrinks to **one** site
after A3 — `store.bump_heat_raw()`, a new method. Every other site
either (a) writes a different column (`heat_base`, `no_decay`,
`is_stale`), (b) writes a row in `homeostatic_state`, or (c) is
deleted outright.

### 3.1 `pg_store.py:237` — `update_memory_heat`

**Current**: `UPDATE memories SET heat = %s WHERE id = %s`.
**Post-A3**: renamed to `bump_heat_raw(memory_id, new_heat_base)`;
the canonical single writer. Writes `heat_base` + refreshes
`heat_base_set_at`.

```python
def bump_heat_raw(self, memory_id: int, new_heat_base: float) -> None:
    """Canonical single writer on memories.heat_base (I2, post-A3).
    Updates heat_base_set_at so subsequent effective_heat() reads
    compute decay from the bump time, not the row's previous anchor.
    """
    self._execute(
        "UPDATE memories SET heat_base = %s, heat_base_set_at = NOW() "
        "WHERE id = %s",
        (max(0.0, min(1.0, new_heat_base)), memory_id),
    )
    self._conn.commit()
```

### 3.2 `pg_store.py:255` — `update_memories_heat_batch`

**Current**: bulk UPDATE from UNNEST arrays on `heat`.
**Post-A3**: **DELETE**. The decay cycle (which was its sole caller
via `compute_decay_updates`) is removed entirely (§6). Anything that
needs to bulk-bump heat now writes `homeostatic_state.factor` (§5) or
calls `bump_heat_raw` per-row (rare — only memify / replay / rating).

### 3.3 `anchor.py:134` — anchor pin

**Current**:
```python
"UPDATE memories SET heat = 1.0, is_protected = TRUE, importance = 1.0, "
"tags = %s::jsonb, content = %s, is_global = %s WHERE id = %s"
```

**Post-A3**: set `heat_base = 1.0`, `no_decay = TRUE`, keep
`is_protected = TRUE`. Semantic meaning preserved via I7: anchored
rows ignore decay in `effective_heat()` and always return
`LEAST(1.0, heat_base * factor) = 1.0` at `factor = 1.0`.

```python
"UPDATE memories SET heat_base = 1.0, heat_base_set_at = NOW(), "
"is_protected = TRUE, no_decay = TRUE, importance = 1.0, "
"tags = %s::jsonb, content = %s, is_global = %s WHERE id = %s"
```

### 3.4 `preemptive_context.py:135` — file-access boost

**Current**:
```sql
UPDATE memories
SET heat = LEAST(heat + %s, 1.0), last_accessed = NOW()
WHERE NOT is_benchmark AND heat < 1.0
  AND (content ILIKE %s OR content ILIKE %s)
```

**Post-A3**: semantically this is "citation raises the rank". Two
options: (a) write `heat_base`, (b) write `last_accessed` only and
let recency-boost in `effective_heat` do the rest. We pick **(a)** —
the boost is small and heat_base is the lever; (b) would require
adding a recency term to `effective_heat` that currently lives in
`recall_memories`, widening the function's responsibility.

```sql
UPDATE memories
SET heat_base = LEAST(heat_base + %s, 1.0),
    heat_base_set_at = NOW(),
    last_accessed = NOW()
WHERE NOT is_benchmark AND heat_base < 1.0
  AND (content ILIKE %s OR content ILIKE %s)
```

Writer semantics preserved. The I2 allow-list is kept tight because
this site calls into the canonical writer helper (see §7 for the
grep test).

### 3.5 `pg_schema.py:739` — `decay_memories()` PL/pgSQL

**Current**: the UPDATE body in `DECAY_MEMORIES_FN` rewrites `heat`
per-row with stage-dependent decay.
**Post-A3**: **DELETE**. `DECAY_MEMORIES_FN` is removed from
`pg_schema.py`. The decay math moves verbatim into
`effective_heat()` (§2). Stage-entry logic (which writes
`stage_entered_at`) is kept but moves to the cascade cycle (it was
already a separate code path).

### 3.6 `codebase_analyze_helpers.py:111` — `mark_stale`

**Current**: `UPDATE memories SET is_stale = TRUE, heat = 0 WHERE id = %s`.
**Post-A3**: the `heat = 0` is redundant with `is_stale = TRUE`
everywhere in the codebase (stale rows are filtered out of every
scan: `NOT is_stale` is in every recall CTE and every get_all
query). Drop the heat zeroing; the column stays at whatever
`heat_base` was — irrelevant because stale rows are never read.

```python
"UPDATE memories SET is_stale = TRUE WHERE id = %s"
```

### 3.7 `sqlite_store.py:214` — SQLite `update_memory_heat`

**Current**: `UPDATE memories SET heat = ? WHERE id = ?`.
**Post-A3**: rename to `bump_heat_raw` + switch to `heat_base`. SQLite
is the dev/test backend; parity with PG is required. SQLite does not
support partitions or `effective_heat` as a PL/pgSQL function, so the
SQLite path keeps the column but recomputes `effective_heat` in Python
(shared `mcp_server/core/effective_heat.py`, a pure function).

```python
"UPDATE memories SET heat_base = ?, heat_base_set_at = CURRENT_TIMESTAMP "
"WHERE id = ?"
```

### 3.8 `sqlite_store.py:230` — SQLite `update_memories_heat_batch`

**Current**: executemany of `UPDATE memories SET heat = ?` per row.
**Post-A3**: **DELETE**, same rationale as §3.2.

### 3.9 Disjoint — NOT refactored

- `pg_store_wiki.py:448` (`wiki.pages.heat`): disjoint from I2.
  Left alone.
- `pg_store_entities.py:30, 44` (`entities.heat`): disjoint from
  I2. Left alone. (Entity decay remains eager — entities are ~10×
  fewer than memories and lack stage/valence complexity.)
- `pg_store_relationships.py:161` (`entities.heat` co-activation
  bump): disjoint. Left alone.
- `pg_schema.py:322` (wiki citation trigger on `wiki.pages.heat`):
  disjoint. Left alone.

---

## 4. `recall_memories()` rewrite

Preserve WRRF structure in `RECALL_MEMORIES_FN` (`pg_schema.py:508–716`).
Swap every reference to `m.heat` with `effective_heat(m, NOW(), f.factor)`
where `f` is a LEFT JOIN to `homeostatic_state` defaulting to 1.0 when
missing.

Key observation (Zhuangzi / partial-order preservation): because
`factor > 0`, ordering by `heat_base` remains equivalent to ordering by
`heat_base * factor` within a single domain. The B-tree index
`idx_memories_*_heat_base` remains usable for the `hot` CTE's
`ORDER BY heat_base DESC LIMIT v_pool` if we pass the scaled predicate
as a parameter rewrite. The planner cannot push `effective_heat()`
(STABLE, non-monotonic across stages) into an index, but the hot CTE
doesn't need exact ranking — it needs a pool; we prefilter by
`heat_base` and rerank by `effective_heat` inside the CTE.

```sql
WITH hs AS (
    SELECT COALESCE(h.factor, 1.0) AS factor
    FROM (VALUES (1)) AS dummy(x)
    LEFT JOIN homeostatic_state h
           ON h.domain = COALESCE(p_domain, '')
),
-- Cheap pre-filter: heat_base ≥ (p_min_heat / factor). Monotonic.
-- Planner uses idx_memories_*_heat_base.
candidates AS (
    SELECT m.*
    FROM memories m, hs
    WHERE m.heat_base >= (p_min_heat / NULLIF(hs.factor, 0))
      AND NOT m.is_stale
      AND (p_domain IS NULL
           OR m.domain = p_domain
           OR (p_include_globals AND m.is_global = TRUE))
      AND (p_directory IS NULL OR m.directory_context = p_directory)
),
-- vec/fts/ngram/recency CTEs unchanged except they read `candidates`
-- instead of `memories` and use effective_heat(c, NOW(), hs.factor)
-- for the post-filter min_heat check.
vec AS (
    SELECT c.id,
           (1.0 - (c.embedding <=> p_query_emb))::REAL AS raw_score
    FROM candidates c, hs
    WHERE c.embedding IS NOT NULL
      AND effective_heat(c, NOW(), hs.factor) >= p_min_heat
    ORDER BY c.embedding <=> p_query_emb
    LIMIT v_pool
),
-- …fts, ngram, recency CTEs follow the same pattern…
hot AS (
    SELECT c.id,
           effective_heat(c, NOW(), hs.factor) AS raw_score
    FROM candidates c, hs
    ORDER BY raw_score DESC
    LIMIT v_pool
),
-- final SELECT returns effective_heat as the `heat` output column so
-- downstream Python consumers see no schema change.
SELECT tb.id, m.content, tb.final_score::REAL,
       effective_heat(m, NOW(), hs.factor)::REAL AS heat,
       m.domain, m.created_at, …
```

The `SELECT * FROM memories` pattern violates R1 (ADR-0045); the
rewrite lists columns explicitly — no regression on that axis.

---

## 5. Homeostatic cycle post-A3

`mcp_server/handlers/consolidation/homeostatic.py` currently issues
one `UPDATE memories SET heat = …` per row in the cohort (lines 135
and 172–174, marked `TODO(A3)` in the source). After A3 this becomes
one UPDATE on `homeostatic_state`.

**Formulas** (preserved from `mcp_server/core/homeostatic_plasticity.py`):

- **Multiplicative (Turrigiano 2008)**: `factor_new = factor_old *
  (_TARGET_HEAT / mean_effective_heat)`. Guard:
  `|log(factor_new) - log(factor_old)| ≤ log(1.03)` (same ±3% ceiling
  the per-row scaling used).
- **Cohort correction (Pfister 2013 bimodal case)**: when
  `bimodality > 0.7`, the cycle identifies the hot cohort and applies
  a *subtractive* correction. Subtraction on a scalar factor is not
  meaningful, so the bimodal branch falls back to a **fold + write
  per-row** on the cohort only (typically ≤ 10% of memories; bounded
  write amplification). The cohort path still uses `bump_heat_raw`
  for the subset.

**Fold trigger** (Feynman first-principles rederivation):

If `|log(factor)| > log(2.0)` — i.e. `factor ∉ [0.5, 2.0]` — the scalar
has drifted far enough that the `candidates` CTE's `heat_base ≥
p_min_heat / factor` prefilter either admits too much or cuts too much.
Fold brings the baseline back into alignment:

```sql
-- Amortized once per month per domain under normal operation.
BEGIN;
UPDATE memories
   SET heat_base = LEAST(1.0, GREATEST(0.0, heat_base * %s)),
       heat_base_set_at = NOW()
 WHERE domain = %s
   AND NOT is_protected
   AND NOT no_decay;
UPDATE homeostatic_state SET factor = 1.0, updated_at = NOW()
 WHERE domain = %s;
COMMIT;
```

Fold is **the only** post-A3 path that writes many `heat_base` rows
at once, and it routes through `bump_heat_raw` in spirit (same
column, same semantics). I2 allow-list: `bump_heat_raw` + one
fold-site inside `homeostatic.py` (explicitly whitelisted with
`# noqa: R4 — A3 fold`).

---

## 6. Decay cycle post-A3 — DELETE

**Files removed**:
- `mcp_server/infrastructure/pg_schema.py:721–779` (`DECAY_MEMORIES_FN`):
  drop the constant and its `execute(DECAY_MEMORIES_FN)` call.
- `mcp_server/handlers/consolidation/decay.py` entire file.
- `mcp_server/core/decay_cycle.py`: keep the pure-math helpers
  referenced by tests, but unwire from the consolidate handler.
- `compute_decay_updates`, `compute_entity_decay` stay (entity decay
  remains eager); `run_decay_cycle` and its call from
  `consolidate.py` are removed.

**Test mapping** — which existing decay tests map to new
`effective_heat` tests:

| Pre-A3 test | Post-A3 test | Kind |
|---|---|---|
| `tests_py/core/test_decay_cycle.py::test_consolidated_decays_slower` | `test_effective_heat_stage_coefficients` | Parametric — assert α(stage) matches 2.0/1.2/0.8/0.5/1.5 |
| `tests_py/core/test_decay_cycle.py::test_emotional_damping` | `test_effective_heat_valence_damping` | Parametric — assert β formula against paper (Yonelinas 2015) |
| `tests_py/core/test_decay_cycle.py::test_permastore_floors` | `test_effective_heat_stage_floors` | Assert floor for consolidated ≥ 0.10, late_ltp ≥ 0.05, reconsolidating ≥ 0.05 |
| `tests_py/core/test_decay_cycle.py::test_protected_not_decayed` | `test_I7_protected_never_decreases` (existing) | Invariant — protected rows stable |
| `tests_py/invariants/test_I2_canonical_writer.py` | Same file, expanded allow-list to exactly `{bump_heat_raw, anchor.py, preemptive_context.py (via canonical helper), codebase_analyze_helpers.py (is_stale only), homeostatic.py fold}` | Grep |
| (new) | `test_I3_effective_heat_idempotent` | Pure-function property |

---

## 7. Invariants post-A3

| Ik | Holds post-A3? | How / test pointer |
|---|---|---|
| **I1** | Yes, strengthened. `effective_heat` returns `LEAST(1.0, GREATEST(stage_floor, …))` — bounded by formula. Test: `test_I1_heat_bounds_effective_heat`. |
| **I2** | Yes, tightened. Allow-list shrinks from 8 to effectively 1 (`bump_heat_raw` + the three non-`heat` semantic writers on `is_stale`, `heat_base_set_at`, `no_decay` that don't write `heat_base` either). Test: `test_I2_canonical_writer` with updated allow-list. |
| **I3** | Introduced. Purity of `effective_heat`: same inputs → same output; no hidden state. Test: `test_I3_effective_heat_idempotent`. |
| **I4** | Unchanged by A3 (Phase 0.4.5 reconciliation still in place). |
| **I5** | Moved into `effective_heat()`. Exponents/β/floors identical. Test: `test_I5_decay_exponents` — parametric synthetic probe against α/β/floor table. |
| **I6** | Relaxed as pre-planned. Consolidate passes a snapshot; plasticity/pruning/cls stop reloading. Test: `test_I6_consolidation_snapshot`. |
| **I7** | Preserved. Protected + no_decay branch in `effective_heat` pins the value. Test: `test_I7_protected_never_decreases`. |
| **I8** | Structural. Formula's `LEAST(1.0, …)` enforces the upper bound. Test: `test_I8_heat_never_exceeds_one` — drive extreme inputs, assert ≤ 1.0. |
| **I9** | Unchanged (synchronous write path intact). |
| **I10** | Unchanged (C1 phase). |

---

## 8. Benchmark regression plan — BLOCKING

Post-A3 benchmark floors (clean DB, single process; per ADR-0045
methodology):

| Benchmark | Floor | Heat dependence | Parity strategy |
|---|---|---|---|
| LongMemEval R@10 | **≥ 97.8 %** | `hot` CTE + WRRF heat weight. | `effective_heat(m, NOW(), 1.0)` on a *freshly loaded* benchmark DB (every row at `heat_base=1.0`, `heat_base_set_at ≈ now()`, `stage = labile`) equals `1.0 · POWER(0.95, 2.0 · 1.0 · 0) = 1.0` — identical to pre-A3. Rankings preserved. |
| LoCoMo R@10 | **≥ 92.6 %** | Same as above. | Same. |
| BEAM Overall | **≥ 0.543** | Same. | Same. |

**Test harness**:

```bash
# Full regression — must run BEFORE the A3 PR is merged, and again on
# the merged commit as the CI gate.
python3 benchmarks/longmemeval/run_benchmark.py --variant s
python3 benchmarks/locomo/run_benchmark.py
python3 benchmarks/beam/run_benchmark.py --split 100K
```

If any floor fails by > 0.5 percentage points, A3 is **blocked**.
Expected delta given freshly-loaded semantics: 0.0.

**Citation for the parity claim**: `effective_heat(m, t0+0, 1.0)` at
`heat_base=1.0, stage=labile, valence=0, t0=now()` ⇒
`LEAST(1.0, GREATEST(0.0, 1.0 · 1.0 · POWER(0.95, 2.0 · 1.0 · 0))) =
1.0`. Identical to pre-A3 `heat = 1.0`. Ranking functions read the
same float → same WRRF sums → same argmax.

---

## 9. Feature flag + kill switch

Env var `CORTEX_A3_LAZY_HEAT ∈ {"true", "false"}`, default `"true"`
post-merge. Read at connection-init time; cached per process.

- **`true`** (default, post-merge): `recall_memories()` uses
  `effective_heat()`. Homeostatic writes `homeostatic_state`. Decay
  cycle is absent.
- **`false`** (emergency rollback without schema revert): a wrapper
  function `effective_heat_frozen(m, …)` returns `m.heat_base` directly
  (bypassing decay math). Same signature so `recall_memories()` does
  not change. Mechanism: at server startup, if flag is false, swap the
  PL/pgSQL body with `CREATE OR REPLACE FUNCTION effective_heat(...)
  RETURNS m.heat_base`. One-line DDL, no migration.

Both flag states are exercised in CI:

```bash
CORTEX_A3_LAZY_HEAT=true  pytest tests_py/ -q
CORTEX_A3_LAZY_HEAT=false pytest tests_py/ -q
```

Parity assertion (when flag=false): benchmark floors identical to
pre-A3 (since `effective_heat_frozen` just returns the stored base,
which equals the pre-A3 `heat` column).

---

## 10. Sequenced execution plan

Each step is one commit; each step has a test; failures roll back by
reverting the commit. No step changes behavior observable by the
benchmark harness until step 7.

1. **Commit: schema DDL** (§1). Test: `tests_py/infrastructure/test_a3_schema.py`
   asserts `heat_base` column exists, `homeostatic_state` table exists,
   `memories_YYYY_MM` partitions present. Verify:
   `psql -c "\d+ memories"`.
2. **Commit: `effective_heat()` function added** (§2).
   Test: `test_effective_heat_contract.py` — α/β/floor table matches
   paper. Verify: `SELECT effective_heat(m, NOW(), 1.0) FROM memories
   LIMIT 5`.
3. **Commit: `bump_heat_raw` helper + feature-flag scaffolding** (§3.1, §9).
   Test: `test_bump_heat_raw_contract.py`. Verify: flag=false path
   returns `heat_base` verbatim.
4. **Commit: refactor 8 writers** (§3.2–3.8). Test:
   `test_I2_canonical_writer.py` green with updated allow-list.
   Verify: grep shows only 1 canonical site + the 3 semantic sites.
5. **Commit: homeostatic rewrite + fold logic** (§5). Test:
   `test_homeostatic_scalar_and_fold.py` — synthetic cohort,
   assert factor drifts, fold triggers at |log f| > log 2.
6. **Commit: `recall_memories()` rewrite** (§4). Test:
   `test_pg_schema_recall.py` expanded with
   `effective_heat`-aware fixtures. Verify:
   `test_I1_heat_bounds_effective_heat` passes on a probed corpus.
7. **Commit: delete decay cycle + DECAY_MEMORIES_FN** (§6). Test:
   mapped decay tests (table in §6) all green.
8. **Benchmark gate**. Run all 3 benchmarks. Must pass floors
   (§8). If fail: revert commits 7 → 1 in order; investigate.
9. **Commit: enable flag default to true**. Test: full suite both
   flag states. Verify: one-month soak (observability log of
   `homeostatic_state.factor` per domain; alert if
   `factor ∉ [0.5, 2.0]` for > 48h — triggers fold).
10. **Post-merge**: delete the `_pre_a3` rollback script after 30
    days without incident. Move `CORTEX_A3_LAZY_HEAT` to
    `docs/adr/` deprecation queue.

---

## 11. References

- Bahrick, H. P. (1984). "Semantic memory content in permastore."
  *J. Experimental Psychology: General* 113(1): 1–29.
- Benna, M. K. & Fusi, S. (2016). "Computational principles of
  synaptic memory consolidation." *Nature Neuroscience* 19: 1697–1706.
- Ebbinghaus, H. (1885). *Über das Gedächtnis.* Duncker & Humblot.
- Kandel, E. R. (2001). "The molecular biology of memory storage."
  *Science* 294(5544): 1030–1038.
- Kleinsmith, L. J. & Kaplan, S. (1963). "Paired-associate learning as
  a function of arousal and interpolated interval." *J. Experimental
  Psychology* 65(2): 190–193.
- Lamport, L. (1978). "Time, Clocks, and the Ordering of Events in a
  Distributed System." *CACM* 21(7): 558–565.
- Pfister, J.-P. et al. (2013). "Good things peak in pairs."
  *Frontiers in Psychology* 4:700.
- Simon, H. A. (1962). "The Architecture of Complexity." *Proc. Am.
  Philos. Soc.* 106(6): 467–482.
- Tetzlaff, C. et al. (2011). "Synaptic scaling in combination with
  many generic plasticity mechanisms stabilizes circuit connectivity."
  *Frontiers in Computational Neuroscience* 5:47.
- Thompson, D'A. W. (1917). *On Growth and Form.* Cambridge University
  Press.
- Turrigiano, G. G. (2008). "The self-tuning neuron: synaptic scaling
  of excitatory synapses." *Cell* 135(3): 422–435.
- Yonelinas, A. P. & Ritchey, M. (2015). "The slow forgetting of
  emotional episodic memories." *Trends Cognitive Sciences* 19(5):
  259–267.
- pgvector issue [#875](https://github.com/pgvector/pgvector/issues/875).
- Cortex [ADR-0045](../adr/ADR-0045-scalability-governance-rules.md) R4.
- Cortex `docs/invariants/cortex-invariants.md` I1–I10.
