# Phase 0.4.5 — memory_entities backfill + reconciliation design

**Status**: design approved, one-shot production execution gated on human
operator sign-off. No production change has been shipped by this task.

**Dependencies**: must land before Phase 2 (JOIN-replacement fixes for
`_find_co_accessed_pairs` and callers) ships.

**Ground-truth files** (absolute paths as of 2026-04-16):
- Backfill SQL: `scripts/phase_0_4_5_backfill.sql`
- Reconciliation core: `mcp_server/core/entity_reconciliation.py`
- Parity test: `tests_py/invariants/test_phase2_parity.py`
- Prior audits: `docs/invariants/cortex-invariants.md` §I4 (Curie)

## 1. Why a naive CROSS JOIN does not scale

Curie's audit SQL (cortex-invariants.md:154–163) is the reference query:

```sql
SELECT e.id, e.name, COUNT(*)
  FROM entities e
  JOIN memories m ON m.content ILIKE '%' || e.name || '%'
  LEFT JOIN memory_entities me
         ON me.entity_id = e.id AND me.memory_id = m.id
 WHERE me.memory_id IS NULL
 ...;
```

On the local `cortex` database (800 memories, 17,094 entities), a naive
`INSERT ... SELECT` built from this shape executed by the default PostgreSQL
planner picks a **Seq Scan on entities + Materialize of memories** plan:

```text
Nested Loop (cost=0..92663, rows=22988) actual=217527ms rows=91765
  Join Filter: (m.content ~~* (('%' || e.name) || '%'))
  Rows Removed by Join Filter: 13489835
  Buffers: shared hit=24583162
  ->  Seq Scan on entities e (rows=16977)
  ->  Materialize (rows=800 each, loops=16977)
```

- Work performed: `17,094 entities × 800 memories × 3.2 kB avg content`
  = **13.67 million ILIKE probes × ~3 kB each ≈ 40 GB of scanned text**.
- Wall-clock: **217.5 s**.

Projected to darval's 66K-memory store with ~100K entities:

- `100,000 × 66,000 = 6.6 billion ILIKE probes`.
- Linear extrapolation from the 800×17K baseline (13.6M probes → 217 s,
  ~62,700 probes/s): **~29 hours** for the naive plan.
- Materialize node RAM: holds the memory set in RAM per-nested-loop-
  iteration. 66K memories × 3 kB ≈ **200 MB per replay**, potentially
  triggering temp-file spill and seq-scan slowdown.

This is not shippable.

## 2. Why the trigram prefilter works

`idx_memories_content_trgm` (pg_schema.py:480–481) is a GIN index over
`gin_trgm_ops` on `memories.content`. `pg_trgm` supports ILIKE
acceleration when the pattern's literal (non-wildcard) portion is ≥ 3
characters. Every entity with `length(name) >= 4` meets that bound (the
Option A filter), so every probe can use the index.

Forcing the planner to use the index (via `SET LOCAL enable_seqscan =
off; SET LOCAL enable_material = off;` inside the transaction) produces:

```text
Nested Loop actual=6660ms rows=91765
  ->  Seq Scan on entities e (rows=16977)
  ->  Bitmap Heap Scan on memories m (loops=16977, actual=0.2..0.4 ms each)
        Recheck Cond: content ~~* ('%' || e.name || '%')
        Rows Removed by Index Recheck: 6
        ->  Bitmap Index Scan on idx_memories_content_trgm (rows=13 avg)
```

- Per-entity cost: **~0.35 ms** (bitmap index scan + 13 candidate rows
  reread from heap with exact ILIKE recheck).
- Total cost: `17,094 × 0.35 ms ≈ 6 s`. Measured: **6.57 s** (with INSERT
  + FK trigger checks), **6.63 s** for the chunked variant.

**This is a 33x speedup on the local DB, and the speedup grows with
scale** because the trigram index's candidate-per-probe count grows
sub-linearly with memory count (content diversity adds unique trigrams;
the index's per-trigram posting lists stay short for rare substrings).

### Projected runtime for 66K memories × 100K entities

Scaling model:
- Per-entity probe cost scales as `O(bitmap_index_cost + k × candidates)`.
- `bitmap_index_cost` is `O(log(total_trigrams))`, effectively constant.
- `candidates` per probe is the number of memories whose content
  contains the entity's trigrams. For rare names, this is small (~5–50
  on the 800-mem sample). For common substrings (e.g. "data"), this can
  balloon to thousands.

Assuming the average per-probe candidate count grows from ~13 (800 mem)
to ~50 (66K mem, linear-ish), and ILIKE recheck cost per candidate
remains ~25 μs:

- Lower bound (rare-name regime, k ≈ 50 candidates, 25 μs each):
  `100,000 × (negligible + 50 × 25 μs) ≈ 100,000 × 1.5 ms = 150 s`
  → **~2.5 minutes**.
- Upper bound (common-substring regime, k ≈ 500 candidates, heap fetch
  cache-cold on 66K content pages):
  `100,000 × (negligible + 500 × 180 μs) ≈ 100,000 × 90 ms = 9000 s`
  → **~2.5 hours**, which *exceeds* the 1h statement_timeout.

**Projected realistic: 5–30 minutes for a one-shot run.** Plan a
maintenance window of **60 minutes** to accommodate the upper-bound
tail. If runtime exceeds 45 minutes, kill the one-shot and switch to
the chunked Section B variant, which progresses in 500-entity
sub-transactions (each ~1 s) and emits NOTICEs.

If runtime exceeds expectation, the chunked variant in Section B of the
SQL script breaks the work into 500-entity sub-transactions and emits
progress notices, so the operator can monitor and kill mid-run without
losing committed progress.

## 3. Backfill execution runbook

### 3.1 Pre-execution

1. **Backup**. The backfill only INSERTs into `memory_entities`. It
   never UPDATEs or DELETEs. A logical backup (`pg_dump -t memory_entities -t entities -t memories -Fc darval > phase_0_4_5_pre.dump`)
   is sufficient; no need for a full cluster dump.
2. **Confirm the Option A policy**. Run:
   ```sql
   SELECT COUNT(*) FROM entities
    WHERE length(name) < 4 OR archived = TRUE;
   ```
   On local `cortex`: **117** (matches audit). If darval's count is
   orders of magnitude larger, stop — the policy needs re-evaluation
   by Curie before proceeding.
3. **Check `idx_memories_content_trgm` exists**:
   ```sql
   SELECT pg_relation_size('idx_memories_content_trgm');
   ```
   If absent, create it first (it is in `pg_schema.py:480–481`, so any
   fresh schema has it). Expected size on 66K mem: ~8 GB (local is
   114 MB for 800 mem → 9.4 GB for 66K assuming linear).
4. **Record before-coverage**:
   ```sql
   SELECT COUNT(*) FROM memory_entities;
   -- and the eligibility count:
   SELECT COUNT(*)
   FROM   entities e
   JOIN   memories m ON m.content ILIKE '%' || e.name || '%'
   WHERE  length(e.name) >= 4 AND NOT e.archived;
   ```
   Save both numbers into the operator log.
5. **Choose execution window**. The transaction holds a row-level
   exclusive lock on affected `memory_entities` rows and a share-row
   lock on `entities`/`memories`. During 2–5 minutes of insertion:
   - `persist_entities` from the write path continues to succeed (it
     inserts different (m_id, e_id) pairs; ON CONFLICT DO NOTHING
     handles the rare collision).
   - `plasticity_cycle` reads `memory_entities` — reads are blocked
     on uncommitted pairs until COMMIT, but the cycle doesn't hold
     locks across transactions. **Risk**: a mid-backfill consolidate
     run could read an inconsistent mid-commit state on one specific
     memory. Mitigation: pause the `consolidate` scheduled job during
     the backfill window. **Run off-hours, under maintenance mode.**

### 3.2 Execution

Section A (one-shot) of `scripts/phase_0_4_5_backfill.sql`:

```bash
psql "$DATABASE_URL" -f scripts/phase_0_4_5_backfill.sql \
  2>&1 | tee /tmp/phase_0_4_5_backfill.log
```

Watch for:
- `INSERT 0 <N>` — N should be close to the eligibility count minus
  the before-coverage count.
- Any `ERROR:` line → roll back (the transaction hasn't COMMITted if
  the error is inside the block).

### 3.3 Post-verification

```sql
-- Coverage must now be ≥ 99% of eligible pairs.
SELECT
  ROUND(100.0 * covered / eligible, 2) AS coverage_pct,
  covered, eligible
FROM (
  SELECT
    (SELECT COUNT(*)
       FROM entities e
       JOIN memories m ON m.content ILIKE '%' || e.name || '%'
       JOIN memory_entities me ON me.memory_id = m.id AND me.entity_id = e.id
      WHERE length(e.name) >= 4 AND NOT e.archived) AS covered,
    (SELECT COUNT(*)
       FROM entities e
       JOIN memories m ON m.content ILIKE '%' || e.name || '%'
      WHERE length(e.name) >= 4 AND NOT e.archived) AS eligible
) t;
```

Expected on darval: `coverage_pct >= 99.00` (pre-backfill: 0.49%).

Also run the I4 parity test (below) against a copy of the production DB
(`pg_dump | pg_restore` to a test cluster) to confirm behavior before
declaring success.

### 3.4 Rollback

If post-verification fails, **do not re-run the backfill**. Instead:

```sql
-- Identify pairs inserted by this backfill. The backfill uses
-- application_name = 'cortex_phase_0_4_5_backfill'; if your DB has
-- pg_stat_activity logging enabled, you can cross-reference.
--
-- Absent logging, the safest rollback is to restore the pre-backup:
-- pg_restore -d darval -t memory_entities phase_0_4_5_pre.dump
--
-- Note: this loses any memory_entities rows inserted by persist_entities
-- during the backfill window. Those should re-populate themselves on
-- the next remember() call that re-creates the mapping, but do capture
-- a post-backfill snapshot first for audit.
```

## 4. Reconcile job specification

Owner module: `mcp_server/core/entity_reconciliation.py`. Pure SQL
builder, no I/O. Invoked by a new stage in
`mcp_server/handlers/consolidate.py` (not yet wired — task not-yet-done;
deferred to the engineer executing the backfill).

### 4.1 Windowing

Both predicates are AND'd:

- `m.created_at > NOW() - interval '<memory_age_days> days'`
  (default 7 days, matches LABILE+EARLY_LTP cascade window).
- `e.created_at > NOW() - interval '<entity_age_hours> hours'`
  (default 24 hours, captures entities that might not yet have been
  linked by the write path).

Window cardinality on darval (projected):
- ~1,000 new memories / 7 days.
- ~50 new entities / 24 hours.
- Cross-product: ~50,000 candidate pairs — but the trigram probe
  reduces this by the per-entity selectivity factor (typically 10%),
  so the reconcile query touches roughly 500–5,000 pairs per run.

**Runtime budget**: < 5 s on the consolidate schedule. Well within the
existing consolidate handler's latency target (5–60 s typical).

### 4.2 Handler wiring (deferred — design only)

Intended shape for `mcp_server/handlers/consolidation/reconcile.py`:

```python
def run_reconcile_cycle(store) -> dict:
    from mcp_server.core.entity_reconciliation import (
        build_reconciliation_sql, build_count_eligible_sql,
        reconcile_leak_ratio, exceeds_leak_threshold,
    )
    count_sql, params = build_count_eligible_sql()
    eligible = store.execute_scalar(count_sql, params)
    insert_sql, params = build_reconciliation_sql()
    reconciled = store.execute_insert_returning_rowcount(insert_sql, params)
    ratio = reconcile_leak_ratio(reconciled, eligible)
    if exceeds_leak_threshold(ratio):
        logger.warning(
            "reconcile leak ratio %.3f exceeds threshold %.3f; "
            "investigate write path (persist_entities)",
            ratio, LEAK_WARNING_THRESHOLD,
        )
    return {
        "reconciled_pairs": reconciled,
        "eligible_pairs": eligible,
        "leak_ratio": ratio,
    }
```

Wire into `_run_always_cycles` in `consolidate.py` between `cascade`
and `homeostatic` (reconcile is always-on, like cascade) so the cycle
runs on every consolidate invocation.

Stats surfaced: `reconciled_pairs`, `eligible_pairs`, `leak_ratio`,
`duration_ms`.

### 4.3 Leak ratio semantics

- **`ratio <= 0.01`** — healthy. Write path is catching entities at
  memory-write time; reconcile is catching only the irreducible
  retroactive-orphan case. No action.
- **`ratio > 0.01`** — WARN log. One of three causes:
  1. `persist_entities` stopped being called (write path regression).
  2. A bulk entity-import happened (new type/category introduced
     wholesale). Expected one-time spike; no action.
  3. The cascade is running more aggressively than before and
     reclassifying entities as archived — reconcile window is
     picking up many re-linkable pairs. Curie-style investigation.

Threshold source: see `entity_reconciliation.LEAK_WARNING_THRESHOLD`
docstring — 0.01 is an empirical upper bound for the retroactive-orphan
rate on darval's 66K store. Not a universal constant; if the system's
write-path ever legitimately produces more orphans (e.g., on-demand
entity extraction deferred to a background worker), raise the threshold
with an ADR explaining the new baseline.

## 5. Parity test spec

Test file: `tests_py/invariants/test_phase2_parity.py`.

### 5.1 Invariant

Let:
- `SUBSTRING(M, E) = {(a, b) : ∃ m ∈ M. name_a, name_b ⊆ m.content, a<b}`
  — the current plasticity scan.
- `JOIN(M, E) = {(a, b) : ∃ m ∈ M. (m, a), (m, b) ∈ memory_entities, a<b}`
  — the Phase 2 replacement scan.

After the backfill runs, the parity predicate is:

```
| SUBSTRING(M, E) △ JOIN(M, E) | / max(|SUBSTRING|, |JOIN|) <= 1%
```

The 1% tolerance accommodates:
- ILIKE vs SQL equality semantics on rare unicode edge cases.
- Tokenization edge cases (name "re" at position 0 matches "recall"
  under substring but not under the `length(name) >= 4` filter —
  handled identically in both paths).
- Race conditions between `persist_entities` running during the test
  and the test's own fixture inserts (conftest isolates this via
  per-test cleanup, so typically 0%).

### 5.2 Cases enumerated in the test

(a) **Normal co-mention**: entity name appears in content, both scans
    find it. Covered in `test_substring_scan_returns_nonempty_set` and
    `test_join_scan_matches_substring_after_backfill`.

(b) **Retroactive-entity-orphan**: substring finds the pair, JOIN
    doesn't — until the backfill runs. Covered in
    `test_retroactive_orphan_case_b` which asserts BOTH the pre-
    backfill empty-JOIN state AND the post-backfill parity.

(c) **Link-without-textual-match**: JOIN finds a pair, substring
    doesn't. Real data rarely hits this because `persist_entities`
    only inserts when the name is present. The ±1% tolerance absorbs
    the residual.

(d) **Case variants**: "Python" entity vs "python", "PYTHON" in
    content. Covered in `test_case_variants_agree`.

(e) **Short-name filter**: length < 4 entities are excluded. Covered in
    `test_short_entity_names_are_excluded`.

Plus two contract tests for the `entity_reconciliation` module itself
(`test_reconciliation_sql_builder_contract`, `test_leak_ratio_contract`).

### 5.3 Running

```bash
pytest tests_py/invariants/test_phase2_parity.py -v
# Requires DATABASE_URL pointing at cortex_test (or any empty PG DB with
# schema initialized). conftest.py auto-cleans tables per test.
```

Expected: 7/7 pass on a DB where schema + `pg_trgm` are available.
Skipped when PG is not reachable (CI without PG).

## 6. Open questions / risks

1. **Entities table has no `idx_entities_created_at`.** The reconcile
   query's `e.created_at > NOW() - interval` predicate will seq-scan
   entities today. On darval with 100K entities, this costs ~30 ms per
   reconcile — tolerable but adding
   `CREATE INDEX CONCURRENTLY idx_entities_created_at ON entities
   (created_at);` would bring it below 1 ms. **Decision deferred to the
   executing engineer; not blocking.** If added, land it in a separate
   migration before Phase 2 wires up the reconcile handler.

2. **`memories.created_at` index exists** (`idx_memories_created_at` per
   the `\d memories` on both local `cortex` and `cortex_test`). The
   reconcile query uses it for the memory-side window — no action
   needed.

3. **Concurrent backfill + write-path**. `ON CONFLICT DO NOTHING` makes
   both safe to interleave, but the backfill holds its row-level
   exclusive locks for ~5 minutes. If a `remember()` call in that
   window hits the same (m_id, e_id), its insert blocks until backfill
   COMMIT. **Mitigation**: run backfill during a maintenance window
   with the consolidate scheduled job paused.

4. **What happens to entities with `name = e.name` ambiguity**
   (two entities with the same name, different `type`)? The backfill
   will link BOTH entity rows to the matching memory. This may inflate
   the parity scan's pair count by entities the current substring
   version already links (since the substring scan also iterates
   every entity individually, it has the same behavior). Parity is
   preserved; the ±1% tolerance absorbs minor differences. **Not a
   known issue on local DB** (no duplicate-name entities found);
   verify on darval before execution:
   ```sql
   SELECT name, COUNT(*) FROM entities WHERE length(name) >= 4
    GROUP BY name HAVING COUNT(*) > 1;
   ```

5. **trigram index storage**. On darval (66K mem × 3.2 kB = ~210 MB of
   content), the trigram index is projected at ~9 GB. If the database
   is near storage cap, verify space before running — the bitmap scan
   pattern's buffer access pattern is heavy (we saw `shared hit=3.3M`
   on local; projected ~270M hits on darval). Not a correctness risk;
   a latency risk if storage is tight and page cache churns.

6. **What if Phase 2 needs a different shape?** The current JOIN-path
   placeholder in the parity test produces `(entity_a, entity_b)` tuples
   with `a < b` — same as the substring path. If Phase 2's replacement
   function ends up returning dict objects with extra fields (e.g.,
   weights), the parity test needs an adapter to strip to the tuple
   shape. Not a design blocker; a test-maintenance task.

## 7. Handoff: what the executing engineer needs to do

Given human approval to run the backfill on darval:

### 7.1 Pre-commands (in order)

1. `pg_dump -Fc -d darval -t memory_entities -t entities -t memories > /var/backups/phase_0_4_5_pre_$(date +%Y%m%d_%H%M).dump`
2. Pause the consolidate scheduled job: `systemctl stop cortex-consolidate.timer`
   (or equivalent per darval's deployment).
3. Record before-coverage (see §3.1 step 4). Save into a runbook log.

### 7.2 Execute

4. `psql "$DATABASE_URL" -f scripts/phase_0_4_5_backfill.sql 2>&1 | tee /var/log/cortex/phase_0_4_5_$(date +%Y%m%d_%H%M).log`
5. Monitor in a second shell:
   ```sql
   SELECT pid, state, wait_event, query_start, LEFT(query, 80)
     FROM pg_stat_activity
    WHERE application_name = 'cortex_phase_0_4_5_backfill';
   ```
   Expected: 1 row, `state = active`, for 2–10 minutes on darval.

### 7.3 Verify

6. Run the coverage query from §3.3. Assert `coverage_pct >= 99.00`.
7. Restore a copy of darval to a test cluster. Run the parity test:
   ```bash
   DATABASE_URL=postgresql://.../darval_copy \
     pytest tests_py/invariants/test_phase2_parity.py -v
   ```
   Assert all 7 tests pass. (The test uses its own synthetic fixture,
   so it runs on the empty-after-cleanup state, not the backfilled
   data — but the fixture exercises the same query path.)
8. If coverage or parity fail: go to §7.5 rollback.

### 7.4 Post-backfill

9. Resume the consolidate scheduled job: `systemctl start cortex-consolidate.timer`.
10. Monitor the next 3 consolidate runs' `reconciled_pairs` and `leak_ratio`
    stats (once the reconcile handler is wired — Phase 2 work). Expected
    `leak_ratio < 0.01`. If not, Curie investigation.
11. After 24 hours with no regression, delete the pre-backup.

### 7.5 Rollback (if verification fails)

12. Do NOT re-run the backfill. Instead:
    ```bash
    psql -d darval -c "TRUNCATE TABLE memory_entities;"
    pg_restore -d darval -t memory_entities /var/backups/phase_0_4_5_pre_*.dump
    ```
    This discards all post-backup inserts (including any from concurrent
    `persist_entities` calls). Those rows will be re-populated by
    subsequent `remember()` calls that re-extract the same entities —
    and by the reconcile job once it's wired up, within the 7-day
    window. **Coverage will temporarily dip but self-heal.**

### 7.6 Deferred tasks (Phase 2, not in this handoff)

- Wire `run_reconcile_cycle` into `consolidate.py`.
- Swap `plasticity._find_co_accessed_pairs` from substring scan to
  JOIN scan (licensed by the parity test passing).
- Optional: add `idx_entities_created_at` for reconcile-query speedup.

## 8. References

- `docs/invariants/cortex-invariants.md` (Curie I4 audit).
- `mcp_server/infrastructure/pg_schema.py:97–105` (memory_entities DDL),
  `:480–481` (trigram index DDL).
- `mcp_server/handlers/consolidation/plasticity.py:115–146`
  (`_find_co_accessed_pairs` — substring path to be replaced by Phase 2).
- `mcp_server/core/write_post_store.py:34–61` (`persist_entities` —
  write-path I9 enforcement, intact).
- PostgreSQL docs on `pg_trgm`:
  https://www.postgresql.org/docs/current/pgtrgm.html (§F.33.2 Index
  Support — ILIKE acceleration guarantees).
- Martin, R. C. (2017). *Clean Architecture* Ch. 22 — the reconcile
  SQL lives in core because it's policy; the handler that runs it is
  the composition root.
