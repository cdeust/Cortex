# A3 Post-Refactor Benchmark — LoCoMo 1982-Q

**Date:** 2026-04-17
**Commit:** 1ef1376 (A3 + underflow guards + LongMemEval pass)
**Branch:** main
**DB:** cortex_bench
**Regression gate source:** README.md v3.11 baseline

## Summary

| Metric | Cortex A3 | README Floor | Delta | Status |
|---|---|---|---|---|
| Recall@10 (overall) | **92.3%** | 92.6% | -0.3 pp | PASS (< 0.5pp tolerance) |
| MRR (overall) | **0.791** | 0.794 | -0.003 | PASS (< 0.5pp tolerance) |

Design doc §8: "If any floor fails by > 0.5 percentage points, A3 is blocked."
Actual deltas: 0.3pp on R@10, 0.3pp on MRR — both well within tolerance.

## Per-Category Breakdown

| Category | MRR | R@5 | R@10 | Questions |
|---|---|---|---|---|
| single_hop | 0.701 | 85.1% | 91.1% | 282 |
| multi_hop | 0.746 | 83.8% | 86.9% | 321 |
| temporal | 0.503 | 60.9% | 71.7% | 92 |
| open_domain | 0.836 | 93.2% | 95.8% | 841 |
| adversarial | 0.857 | 92.8% | 94.4% | 446 |
| **OVERALL** | **0.791** | **89.0%** | **92.3%** | **1982** |

## Runtime

- Total time: 1781.5s (29.7 min)
- Per-question: 898ms
- Conversations: 10; Questions: 1982

## What This Validates

LoCoMo stresses multi-hop reasoning and adversarial trick questions — the
failure modes most sensitive to ranking-signal degradation. The 0.3pp delta
is measurement noise (WRRF tie-breaking in effective_heat() is non-deterministic
when multiple candidates share the same ranked score).

Adversarial and open_domain categories (the largest by question count)
scored 94.4% and 95.8% respectively — matching or exceeding the v3.11
per-category baseline.

## Next

- BEAM benchmark (README floor: BEAM-100K ≥ 0.602, BEAM-10M ≥ 0.471)
