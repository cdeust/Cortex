# Draft reply to darval — issue #14 (A3 delivery update)

**Instructions**: review before posting. Target comment at
https://github.com/cdeust/Cortex/issues/14

---

A3 landed this morning. Posting the delivery update so you know the
scalability refactor is finished and regression-validated before the
next v3.13 tag.

## What A3 changed

Rewrote the heat subsystem around the principle that **heat is a function,
not a stored state vector**:

- `memories.heat` column renamed to `heat_base` (baseline, written once
  per real touch) + `heat_base_set_at` + `no_decay` pin flag.
- New `effective_heat(m, now, factor) REAL` PL/pgSQL function: computes
  the decayed view at read time using Kandel 2001 stage-dependent α,
  Yonelinas & Ritchey 2015 emotional damping β, Bahrick 1984 permastore
  floors. Single source of truth for invariants I1, I5, I7, I8.
- `homeostatic_state(domain PRIMARY KEY, factor REAL)` table. One row per
  domain. The homeostatic cycle writes ONE scalar per run instead of
  per-row Turrigiano scaling across the whole store.
- `recall_memories()` PL/pgSQL rewritten around a `candidates` CTE that
  prefilters on `heat_base >= min_heat / factor` (monotonic transform;
  index still usable). Every CTE reads from candidates; every `m.heat`
  became `effective_heat(c, NOW(), factor)`.
- Decay cycle deleted. `DECAY_MEMORIES_FN` gone. The consolidate
  handler's decay stage now only cools entity heat (D2 out of scope);
  memory decay is lazy.
- Fold fallback: if `|log(factor)| > log(2)` (factor drifts outside
  [0.5, 2.0]), one batched `UPDATE heat_base *= factor, factor = 1`
  writes the accumulated correction back. Amortized to ~once per month
  per domain under normal load.
- All 8 pre-A3 heat writer sites collapsed to one canonical pair
  (`bump_heat_raw` + `update_memories_heat_batch`). I2 invariant
  allow-list shrunk from 11 to 7 sites, all on `heat_base`. Legacy
  `SET heat = ...` pattern fenced off by
  `test_I2_no_legacy_heat_column_writes`.
- Anchor, preemptive_context, mark_stale, pg_store, sqlite_store all
  refactored to the single A3 path. Zero flag-branching in Python —
  the kill switch is a DDL-level `effective_heat_frozen()` swap per
  design doc §9, not a runtime conditional.

## Benchmark regression gate — all three PASS

Ran the full v3.11 benchmark suite against cortex_bench post-A3. Floors
from the README.

| Benchmark | Cortex A3 | README Floor | Delta | Status |
|---|---|---|---|---|
| LongMemEval R@10 (500 Q) | **97.8%** | 97.8% | 0.0 pp | PASS (exact) |
| LongMemEval MRR | **0.881** | 0.882 | −0.001 | PASS (noise) |
| LoCoMo R@10 (1982 Q) | **92.3%** | 92.6% | −0.3 pp | PASS (< 0.5pp) |
| LoCoMo MRR | **0.791** | 0.794 | −0.003 | PASS (< 0.5pp) |
| BEAM-100K MRR (100 Q) | **0.591** | 0.591 | 0.000 | PASS (exact) |
| BEAM-100K R@10 | **79.0%** | 79.0% | 0.0 pp | PASS (exact) |

All deltas are within the 0.5pp measurement-noise tolerance set in the
design doc §8. BEAM-10M runs overnight; adding that result in a follow-up.

The zero-delta on BEAM-100K is the mathematical cleanest case:
benchmarks insert memories with `heat_base_set_at = NOW()` seconds
before the query, so `hours_elapsed ≈ 0` → `POWER(0.99787, 0) = 1.0` →
`effective_heat = heat_base * factor = 1.0 * 1.0 = 1.0` — identical
to the pre-A3 stored `heat = 1.0`. WRRF sums preserved exactly.

## What this means for the `homeostatic` 66% wall-time

The homeostatic cycle now writes one row (`homeostatic_state.factor`)
per run in the common case, regardless of store size. On your 66K store,
that's a 66,000× reduction in heat writes per consolidate run. The
dominant fsync/HOT-violation path from the original field report is
structurally removed, not tuned.

The fold fallback (rare) still writes per-row, but it's bounded by the
domain partition and triggers when the scalar has drifted outside
[0.5, 2.0] — expected ~once/month per domain under steady load. Not
a hot path.

## What's next

- **BEAM-10M overnight** (floor 0.471 with Temporal Context Assembler).
  Result committed tomorrow.
- **Phase 5**: `psycopg_pool` + admission control + separate batch
  connection. This is the throughput side; A3 was the write-amplification
  side.
- **v3.13.0 tag** after BEAM-10M confirms the full regression envelope.

If you'd run `consolidate` on your store after tag cut and post the
new JSON, it closes the 66%-wall-time loop from your original report.

Commits for the A3 landing (main branch):
- [`5e15a0b`](https://github.com/cdeust/Cortex/commit/5e15a0b) — single A3 path, legacy deleted
- [`1db5ee3`](https://github.com/cdeust/Cortex/commit/1db5ee3) — effective_heat underflow guards
- [`1ef1376`](https://github.com/cdeust/Cortex/commit/1ef1376) — LongMemEval 500-Q PASS
- [`a071d89`](https://github.com/cdeust/Cortex/commit/a071d89) — LoCoMo 1982-Q PASS
- [`d5b6711`](https://github.com/cdeust/Cortex/commit/d5b6711) — BEAM-100K PASS

Cheers.
