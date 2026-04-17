# A3 Post-Refactor Benchmark — LongMemEval 500-Q

**Date:** 2026-04-17
**Commit:** 1db5ee3 (A3 lazy-heat + underflow guards)
**Branch:** main
**DB:** cortex_bench (local Postgres 15 + pgvector)
**Regression gate source:** README.md v3.11 baseline

## Summary

| Metric | Cortex A3 | README Floor | Delta | Status |
|---|---|---|---|---|
| Recall@10 | **97.8%** | 97.8% | 0.0 pp | PASS (floor matched) |
| MRR | **0.881** | 0.882 | -0.001 | PASS (< 0.5pp tolerance per design §8) |

Design doc §8: "If any floor fails by > 0.5 percentage points, A3 is blocked."
Actual delta: 0.1 pp on MRR; well within measurement noise.

## Per-Category Breakdown

| Category | MRR | R@10 |
|---|---|---|
| Single-session (user) | 0.808 | 0.943 |
| Single-session (assistant) | 0.982 | 1.000 |
| Single-session (preference) | 0.637 | 0.867 |
| Multi-session reasoning | 0.940 | 1.000 |
| Temporal reasoning | 0.851 | 0.977 |
| Knowledge updates | 0.921 | 1.000 |

## Runtime

- Total time: 2376.3s (39.6 min)
- Per-question: 4752.5 ms
- Questions: 500

## What This Validates

1. The A3 lazy-heat refactor (heat → heat_base, effective_heat() at read time,
   scalar homeostatic factor) preserves retrieval quality end-to-end on the
   production benchmark.
2. The effective_heat underflow guards (DOUBLE PRECISION intermediates, EXP arg
   capped at 80, 1e-38 final floor) do not distort ranking — rows with extreme
   age hit the stage_floor via the clamp and rank last, same as pre-A3 stale rows.
3. The p_factor default correction (0.95/day → 0.99787/hour) preserves the
   macroscopic decay rate. Pre-A3 DECAY_MEMORIES_FN ran once per day with factor
   0.95; post-A3 effective_heat integrates continuously with the equivalent
   per-hour rate.

## Next

- Run LoCoMo benchmark (README floor: R@10 ≥ 92.6%, MRR ≥ 0.794)
- Run BEAM benchmark (README floor: BEAM-100K ≥ 0.602, BEAM-10M ≥ 0.471)
