# A3 Post-Refactor Benchmark — BEAM-100K

**Date:** 2026-04-17
**Commit:** a071d89 (A3 + LongMemEval + LoCoMo passed)
**Branch:** main
**DB:** cortex_bench
**Regression gate source:** README.md v3.11 baseline
  (`benchmarks/beam/variance/baseline_limit5.txt`)

## Apples-to-Apples (5 conv / 100 Q, WRRF flat baseline)

Matching the v3.11 baseline configuration exactly:

| Metric | Cortex A3 | README v3.11 | Delta | Status |
|---|---|---|---|---|
| Overall MRR | **0.591** | 0.591 | 0.000 | PASS (exact match) |
| R@5 | **73.0%** | 73.0% | 0.0 pp | PASS |
| R@10 | **79.0%** | 79.0% | 0.0 pp | PASS |

Design doc §8 floor (0.5pp tolerance): satisfied by wide margin.

### Per-Ability Breakdown (limit=5)

| Ability | MRR (A3) | R@10 | Qs | Paper LIGHT |
|---|---|---|---|---|
| abstention | 0.400 | 40.0% | 10 | 0.750 |
| contradiction_resolution | 0.817 | 100.0% | 10 | 0.050 |
| event_ordering | 0.380 | 60.0% | 10 | 0.266 |
| information_extraction | 0.543 | 70.0% | 10 | 0.375 |
| instruction_following | 0.448 | 80.0% | 10 | 0.500 |
| knowledge_update | 0.850 | 100.0% | 10 | 0.375 |
| multi_session_reasoning | 0.812 | 100.0% | 10 | 0.000 |
| preference_following | 0.442 | 80.0% | 10 | 0.483 |
| summarization | 0.271 | 60.0% | 10 | 0.277 |
| temporal_reasoning | 0.950 | 100.0% | 10 | 0.075 |
| **OVERALL** | **0.591** | **79.0%** | **100** | **0.329** |

Cortex beats the paper's LIGHT (Llama-4-Maverick LLM-as-judge QA) on 6 of
10 abilities. temporal_reasoning at 0.950 and knowledge_update at 0.850
remain standout categories.

## Full Split (20 conv / 395 Q — exploratory, not a baseline)

Running the full BEAM-100K 20-conversation set (not the v3.11 5-conv
subset) yields MRR 0.442 / R@10 62.4%. This reflects the natural
difficulty spread across 20 conversations vs the curated 5-conv v3.11
subset — not an A3 regression. Recorded for completeness; NOT compared
against the README floor because the README floor itself was measured
on 5 conversations.

## Runtime

- Total time: 259.2s (4.3 min)
- Per-conversation: 51.8s
- Conversations: 5; Questions: 100

## Why Zero Delta

Benchmark rows are inserted with `heat_base_set_at = NOW()` seconds
before the recall query. `effective_heat()` with `hours_elapsed ≈ 0`
returns `heat_base * factor = 1.0 * 1.0 = 1.0` for every row —
identical to the pre-A3 stored `heat = 1.0`. Rankings therefore
preserve perfectly through the A3 refactor: WRRF sums identical, argmax
identical, MRR identical, Recall identical.

## Next

- BEAM-10M (README floor: 0.471 with Temporal Context Assembler).
  Deferred to tonight per user direction. Longer wall-clock run.
