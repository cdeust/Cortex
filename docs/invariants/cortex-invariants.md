# Cortex Scalability Invariants I1–I10

**Phase 0.3 artifact** of the [Cortex Scalability Program](../program/).

Every predicate below is stated precisely enough that two engineers
independently implementing the test should produce equivalent checks.

**Ground-truth sources**: all references below cite absolute file paths in
the Cortex repository as of 2026-04-16.

## Ambiguities resolved from the informal audit brief

- **A1**. The informal statement gave stage exponents "late_ltp 0.7,
  reconsolidating 1.0". The actual code at `pg_schema.py:748–756` uses
  `late_ltp 0.8` and `reconsolidating 1.5`. I5 is restated against code
  ground truth.
- **A2**. I3 says "t_now − t_access" — but stage-dependent decay (I5)
  also consumes `stage_entered_at` and `emotional_valence`
  (`pg_schema.py:757–759`). Post-A3, `effective_heat` must take
  `(raw, t_now − t_access, stage, stage_entered_at, valence)`.
- **A3**. I7 says "anchored memory's heat never drops below 1.0".
  Technically `anchor.py:134` only writes `heat=1.0` at anchor time;
  nothing re-saturates it if something else mutates it. The correct
  post-condition: **no mutating cycle decreases the heat of a row where
  `is_protected = TRUE`**.
- **A4**. I8: "does not exceed 1.0". Today this is two UPDATE sites both
  using LEAST. The post-A3 form is: `effective_heat(m, t) ≤ 1.0 ∀ m, t`,
  which follows from the formula's structure, not from per-site guards.
- **A5**. I10: "pool capacity ≥ max concurrent DB consumers". "Max
  concurrent consumers" is workload-dependent; restated as a *structural*
  invariant: "pool is configured with `max ≥ N` where `N` is the number
  of registered cycle workers + 1 for hot path", so testable without
  running a full workload.

## 1. Invariants table

| # | Formal predicate | Type | A3 refinement |
|---|---|---|---|
| **I1** | `∀ m ∈ memories. 0.0 ≤ m.heat ≤ 1.0` | State | **Changes.** Stored `heat` becomes `heat_raw`; invariant moves to the *read path*: `∀ m. 0.0 ≤ effective_heat(m, now) ≤ 1.0`. |
| **I2** | `|{call-sites that issue UPDATE ... SET heat ... ON memories}| = 1` — the canonical writer. Today: 5 sites; target post-A3: 0 sites on `memories.heat` (column becomes `heat_raw`, written only at insert + explicit boost calls through a single helper). | Trace (static) | **Changes.** Becomes: `|{call-sites that compute effective_heat}| = 1`, and `memories.heat_raw` is never `UPDATE`'d outside `store.bump_heat_raw()`. |
| **I3** | `∀ m, t. effective_heat(m, t) = f(m.heat_raw, t − m.last_accessed, m.stage, m.stage_entered_at, m.valence)` is a pure function (deterministic, no hidden state), and for any `t1 = t2`, with no intervening writes, `effective_heat(m, t1) = effective_heat(m, t2)`. | Trace (idempotency) | **Introduced by A3.** Not meaningful pre-A3 (heat is mutable). |
| **I4** | **Eventual form** (post Phase 0.4.5 reconciliation job): `∀ m ∈ memories. ∀ e ∈ entities where length(e.name) ≥ 4 ∧ ¬e.archived ∧ lower(m.content) ⊇ lower(e.name). ∃ link ∈ memory_entities. link.memory_id = m.id ∧ link.entity_id = e.id` holds within 24h of any write. **Immediate form** (synchronous write-path): `∀ write(m). persist_entities(m)` runs before the write transaction commits. | State + Trace | **Preserved with reconciliation.** Restated post-Curie audit: the original "immediate" form is violated at ~99.5 % coverage today (entities added after a memory are never back-linked). Phase 0.4.5 introduces `reconcile_memory_entities` (windowed daily job) to establish eventual consistency; A3 does not change the invariant. |
| **I5** | `∀ m ∈ memories. after decay_step(m): m.heat' = GREATEST(floor(m.stage), m.heat · p_factor^(α(stage) · β(valence, Δt_stage)))` where `α(labile)=2.0, α(early_ltp)=1.2, α(late_ltp)=0.8, α(consolidated)=0.5, α(reconsolidating)=1.5, α(NULL)=1.0` and `β = 1 − 0.30 · |valence| · (1 − exp(−Δt_stage / 3600))`; `floor(consolidated)=0.10, floor(late_ltp)=0.05, floor(reconsolidating)=0.05, floor(else)=0.0`. | Trace (transition) | **Changes.** Migrates into `effective_heat()`. The floor/α/β coefficients become parameters of the pure function, not side-effects of a cycle. |
| **I6** | For a single `consolidate()` run `r`, let `σᵢ = {(m.id, m.heat) | m ∈ memories_seen_by(stageᵢ)}`. Then `∀ stageᵢ, stageⱼ ∈ r.stages. σᵢ = σⱼ` — except for stages that have declared themselves mutators-before-stageⱼ in the happens-before order. | Trace | **Relaxed.** Post-A3, torn reads of `heat_raw` are harmless if readers use `effective_heat`. New form: all stages read the same `memories` snapshot; deltas to `heat_raw` batched at end-of-run. |
| **I7** | `∀ cycle c ∈ {decay, homeostatic, memify, deep_sleep, pruning, plasticity}. ∀ m where m.is_protected = TRUE ∨ m.is_stale = TRUE. heat(m, after c) ≥ heat(m, before c)` for `is_protected` AND `c does not modify m` for `is_stale`. | Trace (transition) | **Preserved.** |
| **I8** | `∀ m, t. effective_heat(m, t) ≤ 1.0`. Today: `∀ UPDATE site that bumps heat. new_heat = LEAST(old + δ, 1.0)`. | State (post-A3) / Trace (pre-A3) | **Strengthened.** Becomes a structural property of the `effective_heat` formula, not a per-site guard. |
| **I9** | `∀ memory m written at time tw. persist_entities(m) →hb any_read_of(memory_entities, m.id)`. In particular: `persist_entities(m) →hb plasticity_cycle.co_access_for(m)`. | Trace (happens-before) | **Preserved.** |
| **I10** | `pool.max ≥ |{registered cycle workers}| + 1` (the `+1` reserves the hot/read path). Today no pool (single `_conn`); trivially false as equality. Post-C1: `psycopg_pool(min=2, max=8)` with registered workers ≤ 7. | State (config) | **Strengthened.** Becomes: `pool.max ≥ max_concurrent_cycle_depth + 1`, checked at server start. |

## 2. Happens-before diagrams

### I2 — canonical heat writer (pre- vs post-A3)

```
Pre-A3 (today, 5 writers, unordered):
  pg_store.update_memory_heat ────┐
  pg_store.update_memories_heat_batch ────┐
  anchor.handler (UPDATE heat=1.0)    ────┼───▶  memories.heat
  preemptive_context.prime            ────┤      (shared mutable)
  pg_schema.decay_memories()          ────┘
  pg_store_wiki.apply_thermo_decisions ───▶  wiki.pages.heat
                                             (disjoint, OK)

Post-A3 (target, 1 writer + lazy read):
  store.bump_heat_raw(id, δ)  ───▶ memories.heat_raw   (only mutator)
  read_memory(id)             ───▶ effective_heat(row, now())  [pure]
  decay/consolidation         ───▶ NO writes to heat_raw
                                    (they may write stage, stage_entered_at)
```

### I6 — consolidation snapshot ordering (current violation)

```
consolidate.handler() {
  t0: memories := store.load_hot_memories()        # ONE snapshot
  t1: decay(memories)                ────┐
  t2: plasticity(store) ◀── VIOLATION ── only call without `memories`
  t3: pruning(store)                 ── also no `memories`, pure-graph
  t4: compression(memories)          ────┤  same σ
  t5: cls(store, embeddings)         ── reloads memories internally
  t6: memify(memories)               ────┤  same σ
  t7: homeostatic(memories)          ────┤  same σ
  t8: deep_sleep(memories)           ────┘  same σ
}

Guaranteed happens-before:  t0 →hb tᵢ for i in {1, 4, 6, 7, 8}
MISSING happens-before:     t0 →hb t2   (plasticity reads fresh)
                            t0 →hb t3   (pruning reads fresh)
                            t0 →hb t5   (cls reads fresh)
```

### I9 — entity write must precede plasticity read

```
remember(content) {
    store.insert_memory(m)       ── m.id assigned
              │
              ▼
    persist_entities(m)          ── inserts into entities + memory_entities
              │                     SYNCHRONOUS in write path
              ▼                     (write_post_store.py:60)
    store._conn.commit()         ── transaction closes
}
              │   (happens-before via DB serialization order)
              ▼
consolidate() {
    plasticity.run_plasticity_cycle(store) {
        get_all_relationships()  ── reads memory_entities
        co_access_scan(memories) ── depends on memory_entities complete
    }
}

If persist_entities() were moved to async/background:
  MUST introduce an explicit barrier (hb edge) before plasticity reads.
```

## 3. Executable tests

The full test code suite is organized under `tests_py/invariants/`.
This document cites the structural contracts each test must satisfy;
see the [Lamport handoff file](../../tasks/lamport-invariant-tests.md)
for ready-to-drop code blocks.

Summary of tests (one per invariant):

| # | Test location | Type | Runtime budget |
|---|---|---|---|
| I1 | `test_I1_heat_bounds.py` | state-level SQL count | < 100 ms |
| I2 | `test_I2_canonical_writer.py` | static AST/grep | < 2 s |
| I3 | `test_I3_effective_heat_idempotent.py` | post-A3 property | < 5 s |
| I4 | `test_I4_entity_coverage.py` | state-level SQL | < 5 s |
| I5 | `test_I5_decay_exponents.py` | parametric synthetic probe | < 10 s |
| I6 | `test_I6_consolidation_snapshot.py` | trace via monkeypatch | < 30 s |
| I7 | `test_I7_protected_never_decreases.py` | trace via synthetic cycle | < 10 s |
| I8 | `test_I8_heat_never_exceeds_one.py` | state-level (redundant w/ I1) | < 100 ms |
| I9 | `test_I9_entity_write_before_plasticity.py` | trace via monkeypatch | < 5 s |
| I10 | `test_I10_pool_capacity.py` | config check | < 100 ms |

All tests: deterministic, fast (< 30 s each), CI-gated.

## 4. Audit queries (detect current violations)

```sql
-- I1: heat bounds (expect 0 rows)
SELECT id, heat FROM memories WHERE heat < 0.0 OR heat > 1.0;

-- I4: dangling memory_entities (expect 0)
SELECT me.* FROM memory_entities me
LEFT JOIN memories m ON m.id = me.memory_id
LEFT JOIN entities  e ON e.id = me.entity_id
WHERE m.id IS NULL OR e.id IS NULL;

-- I4 weaker (Curie audit — post-extraction orphans): how many entity
-- names textually match content but have no memory_entities row?
SELECT e.id, e.name, COUNT(*) AS missing_links
  FROM entities e
  JOIN memories m ON m.content ILIKE '%' || e.name || '%'
  LEFT JOIN memory_entities me
         ON me.entity_id = e.id AND me.memory_id = m.id
 WHERE me.memory_id IS NULL
 GROUP BY e.id, e.name
 ORDER BY missing_links DESC
 LIMIT 100;

-- I7: protected heat monotonicity
--   Snapshot heat for is_protected rows, run consolidate, diff the
--   heat column; any row whose after < before is a violation.
SELECT id, heat FROM memories WHERE is_protected = TRUE;  -- before
SELECT run_consolidate();                                 -- (pseudo)
SELECT id, heat FROM memories WHERE is_protected = TRUE;  -- after

-- I9: recent memories without any memory_entities row
SELECT m.id, m.content
  FROM memories m
 WHERE m.created_at > NOW() - interval '1 day'
   AND NOT EXISTS (
       SELECT 1 FROM memory_entities me WHERE me.memory_id = m.id
   )
 ORDER BY m.created_at DESC
 LIMIT 100;

-- I10 (post-C1): the running Cortex process logs pool stats on boot.
--   `SHOW max_connections` on PG; `pool.get_stats()` on app side.
```

## 5. Invariant evolution (pre-A3 → post-A3)

| # | Pre-A3 form | Post-A3 form | Migration step |
|---|---|---|---|
| I1 | `memories.heat ∈ [0,1]` stored | `effective_heat(m, now) ∈ [0,1]` computed; `heat_raw ≥ 0`, upper bound by structure | Rename column; add function; add `CHECK (heat_raw ≥ 0)`. |
| I2 | 5 known writer sites | 1 writer (`bump_heat_raw`); readers use `effective_heat` | Replace call-sites in 4 files; grep test tightens allow-list. |
| I3 | N/A | Purity + idempotency of `effective_heat` | New stored function; test added as A3 merge gate. |
| I4 | Join-table coverage at write time | Unchanged | — |
| I5 | Inside `decay_memories()` UPDATE body | Inside `effective_heat()` body | Extract CASE expression; decay cycle stops updating heat, only updates `stage_entered_at` and floor adjustments. |
| I6 | Violated by plasticity / pruning / cls | Relaxed: all stages read one snapshot; writes batched at run end; torn reads of `heat_raw` harmless because readers use `effective_heat` | Pass `memories` to plasticity/pruning/cls; add batched writer. |
| I7 | Decay SQL filters `NOT is_protected` | Same; plus `effective_heat` respects `is_protected` as a pinning predicate (returns `max(1.0, …)`) | Add `is_protected` branch inside `effective_heat`. |
| I8 | LEAST guard at each writer | Structural: formula is `min(1.0, …)` by construction | Drop per-site LEAST; rely on formula. |
| I9 | Synchronous in write path | Synchronous; if ever made async, add explicit barrier before plasticity | No code change at A3; ADR required if C-phase ever reorders. |
| I10 | Single conn; trivially passes | `pool.max ≥ workers + 1` | C1 introduces `psycopg_pool`; test begins to bind. |

## 6. CI integration (which Ik gates which phase)

| Phase | Blocking | Advisory (warn only) |
|---|---|---|
| **P0.3 (today)** | I1, I4 (strict referential), I7, I8 | I2 (logged; expected to fail), I6 (logged; 3 known stages), I9 (logged), I10 (skipped) |
| **P1 (fragility sweep)** | I1, I4, I5 (exponent regression), I7, I8, I9 | I2, I6 |
| **A3 merge gate** | I1 (new form), I2 (strict: only canonical writer), I3 (new), I5 (moved into `effective_heat`), I7, I8 | I6 (relaxed), I10 |
| **C1 merge gate** | all above + I10 (strict) | — |
| **Steady state (post-C1)** | I1, I2, I3, I4, I5, I6 (full), I7, I8, I9, I10 | — |

**Gate implementation**: add a `pytest -m invariants` marker. CI runs it
after unit tests. A blocking invariant failing = red build. An advisory
invariant failing = yellow status + logged counterexample at
`tasks/invariant-counterexamples/<date>.md`.

## 7. Hand-offs

- **Implementation of `effective_heat` (A3)**: engineer. The formula is
  fully specified in I5 + I8; no design questions remain.
- **Pool sizing calibration (I10 concrete N)**: Shannon (find the right
  quantity) + Curie (measure concurrent cycle depth on 66K store).
- **Priority/failure ordering of cycles under relaxed I6**: Hamilton
  (priority-displaced scheduling under overload).
- **Node-level measurement of decay drift vs theoretical I5**: Curie
  (run synthetic-probe harness across stages, plot residuals).

## 8. References

- Lamport, L. (1978). *"Time, Clocks, and the Ordering of Events in a
  Distributed System."* CACM 21(7): 558–565. — happens-before.
- Lamport, L. (1977). *"Proving the Correctness of Multiprocess
  Programs."* IEEE TSE SE-3(2): 125–143. — invariants as correctness
  primitives.
- Simon, H. A. (1962). *"The Architecture of Complexity."* — near-
  decomposability, which frames the invariant bundle.
- Cortex [ADR-0045](../adr/ADR-0045-scalability-governance-rules.md)
  (R1–R6 governance rules).
- pgvector issue
  [#875](https://github.com/pgvector/pgvector/issues/875) — HNSW UPDATE
  maintenance.

**Ground-truth files (consulted, paths absolute as of 2026-04-16):**
- `mcp_server/infrastructure/pg_schema.py` (CHECK at line 215;
  `DECAY_MEMORIES_FN` at 721–779; citation heat bump at 322)
- `mcp_server/infrastructure/pg_store.py` (heat writers at 237 and 255)
- `mcp_server/infrastructure/pg_store_wiki.py`
  (`apply_thermo_decisions` at 448 — `wiki.pages`, disjoint from I2)
- `mcp_server/handlers/anchor.py` (UPDATE at 134)
- `mcp_server/hooks/preemptive_context.py` (UPDATE at 135)
- `mcp_server/handlers/consolidate.py` (`_run_cycles` at 163–196;
  plasticity call without `memories` at 179)
- `mcp_server/handlers/consolidation/plasticity.py` (signature at 17–20;
  `memories` is optional but consolidate doesn't pass it)
- `mcp_server/core/write_post_store.py` (synchronous
  `persist_entities` at 42–61)
