# BEAM-10M paired oracle-vs-temporal reproduction — current code (2026-06-11)

Purpose: test whether the April finding (label-free temporal stage detection
outperforms oracle plan_id; artefacts benchmarks/beam/variance/
assembler_10m_{stagefixed,temporal}.txt, in the history at 1bfbc459, 0.429 vs 0.471) survives the
bounded-I/O code revisions.

## Protocol
- Code: commit 6112f87 era (current main, 2026-06-11).
- Both runs: BEAM-10M split, 10 conversations, 196 questions,
  CORTEX_USE_ASSEMBLER=1, fresh dedicated DB per run.
- Oracle run (this directory): CORTEX_STAGE_DETECTOR unset -> default "oracle"
  (plan_id ground truth). DB cortex_bench_10m_paired (created empty same day).
  Raw stdout: 20260611-oracle-currentcode.log (11.7 MB, out of the tree since
  issue #705: `git show 1bfbc459:benchmarks/results/beam10m_paired/20260611-oracle-currentcode.log`).
- Temporal run: CORTEX_STAGE_DETECTOR=temporal, overnight chain 2026-06-11,
  clean bench DB. OVERALL MRR 0.523, R@10 59.3%.

## Oracle (plan_id) result — current code
```
Ability                         MRR    R@5   R@10   Qs   LIGHT
abstention                    0.750 75.0% 75.0%   20   0.750
contradiction_resolution      0.817 90.0% 90.0%   20   0.050
event_ordering                0.138 20.0% 20.0%   20   0.266
information_extraction        0.516 75.0% 75.0%   20   0.375
instruction_following         0.154 25.0% 25.0%   20   0.500
knowledge_update              0.942 100.0% 100.0%   20   0.375
multi_session_reasoning       0.558 75.0% 75.0%   20   0.000
preference_following          0.450 65.0% 65.0%   20   0.483
summarization                 0.230 50.0% 50.0%   16   0.277
temporal_reasoning            0.408 50.0% 50.0%   20   0.075
OVERALL                       0.496 62.5% 62.5%  196   0.329
```

## Paired comparison
| pair (code revision) | oracle MRR | temporal MRR | Δ (temporal−oracle) | oracle R@10 | temporal R@10 |
|---|---|---|---|---|---|
| 2026-04 (a5c1684 era) | 0.429 | 0.471 | +0.042 | 53.7% | 53.1% |
| 2026-06-11 (current) | 0.496 | 0.523 | +0.027 | 62.5% | 59.3% |

The temporal MRR advantage REPRODUCES on current code (+0.027); in both pairs
oracle holds a small R@10 edge while temporal wins MRR (better ranking of the
gold memory when found). Compare within pairs only — the two pairs are
different code revisions.
