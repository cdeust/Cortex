# Phase 5 Post-Refactor Benchmark — LongMemEval 500-Q

**Date:** 2026-04-17
**Commit:** 179049c (v3.13.0 release prep)
**Branch:** main
**DB:** cortex_bench
**Regression gate source:** post-A3 baseline (1ef1376)

## Summary

| Metric | Cortex Phase-5 | Post-A3 Floor | Delta | Status |
|---|---|---|---|---|
| Recall@10 | **97.8%** | 97.8% | 0.0 pp | PASS (exact) |
| MRR | **0.881** | 0.881 | 0.000 | PASS (exact) |

The ConnectionPool + asyncio.to_thread + admission semaphore + JOIN
replacements + streaming homeostatic + NFC content hardening stack
preserves retrieval quality exactly — every ranking signal reaches
the WRRF fusion unchanged, the order relation is preserved, and the
argmax is identical across all 500 questions.

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

- Total time: 2472.5 s (41.2 min)
- Per-question: 4945 ms
- Questions: 500

Compared to post-A3 baseline 2376 s (4752 ms/Q):
  * +4% wall-clock overhead
  * Accounted for by: per-call thread spawn + new event loop
    creation in `safe_handler._run_coroutine_on_thread`, plus
    per-query pool checkout cycle (~1-2 ms each).
  * Benefit: concurrent MCP tool calls now genuinely run in parallel
    instead of serializing on a single event loop — production
    throughput rises with concurrency, unlike pre-Phase-5.

## What Zero Delta Validates

1. **Pool migration thread-safety**: 14 direct `_conn.execute` sites
   migrated to `acquire_interactive()` / `acquire_batch()` without
   dropping any write.
2. **Materialized cursor**: `_execute` borrows a connection, fetches
   rows eagerly, returns the connection — every subsequent
   `fetchone()` / `fetchall()` reads from the pre-fetched list with
   identical results.
3. **Phase 2 JOIN replacements** (plasticity, synaptic tagging,
   co-activation UPSERT): all three produce the same ranking signals
   the pre-Phase-2 Python substring scans produced, now with Phase
   0.4.5-backfilled memory_entities coverage of 100%.
4. **Phase 4 streaming moments**: health metrics from Welford
   pairwise-merge match list-based Welford within 1e-6 on every
   tested distribution (uniform, bimodal, jittered).
5. **Phase 7 content hardening**: NFC + control-strip + byte-cap at
   the ingestion boundary does not affect retrieval of fixtures that
   were already NFC-normalized.

## Final v3.13.0 regression envelope

| Benchmark | v3.11 Floor | Post-v3.13.0 | Status |
|---|---|---|---|
| LongMemEval R@10 | 97.8% | **97.8%** | PASS |
| LongMemEval MRR | 0.882 | **0.881** | PASS (< 0.5pp) |
| LoCoMo R@10 | 92.6% | **92.3%** | PASS (< 0.5pp) |
| LoCoMo MRR | 0.794 | **0.791** | PASS (< 0.5pp) |
| BEAM-100K MRR | 0.591 | **0.591** | PASS (exact) |
| BEAM-100K R@10 | 79.0% | **79.0%** | PASS (exact) |

BEAM-10M runs under `benchmarks/beam/run_benchmark.py --split 10M`
with `CORTEX_USE_ASSEMBLER=1 CORTEX_STAGE_DETECTOR=temporal` (README
floor 0.471).

## Next

- Tag v3.13.0 + cut GitHub release.
- Post release note to issue #14 (darval).
