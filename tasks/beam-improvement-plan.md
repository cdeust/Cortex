# BEAM Improvement Plan — Research Synthesis

**Date:** 2026-04-06
**Baseline:** BEAM MRR 0.543 (100K split, clean DB)

## Priority-Ordered Improvements

### Phase 1: Instruction + Preference (highest combined impact)

**Paper basis:** ENGRAM (arxiv 2511.12960), HiMem (arxiv 2601.06377)

| Step | Change | File | Impact |
|---|---|---|---|
| 1a | Instruction tagging at ingestion | memory_decomposer.py, memory_ingest.py | Prerequisite |
| 1b | PREFERENCE intent classification | query_intent.py | Prerequisite |
| 1c | Tag-boost signal in recall_memories PL/pgSQL | pg_schema.py | +0.10-0.15 MRR on pref/instr |
| 1d | Preference query expansion templates | enrichment.py | +0.05-0.10 MRR |
| 1e | Per-type pool guarantee (ENGRAM-style) | pg_recall.py, pg_schema.py | +0.15-0.25 MRR |

Expected: instruction 0.244 → 0.40-0.50, preference 0.374 → 0.50-0.60

### Phase 2: Summarization — MMR diversity (implemented, pending validation)

**Paper basis:** Carbonell & Goldstein (SIGIR 1998)

Already implemented: mmr_diversity.py, wired in pg_recall.py for SUMMARIZATION intent.
Lambda=0.5, candidate pool 2x for summarization queries.
Expected: summarization 0.391 → 0.50-0.55

### Phase 3: Event Ordering — Query-anchored temporal scoring

**Paper basis:** MRAG (Zhang et al., EMNLP 2025, arxiv 2412.15540)

| Step | Change | File | Impact |
|---|---|---|---|
| 3a | Temporal constraint extraction (regex) | temporal.py | Prerequisite |
| 3b | MRAG piecewise spline scoring | temporal_anchor.py (new) | Core mechanism |
| 3c | Multiplicative post-retrieval fusion | pg_recall.py | +0.05-0.10 MRR event ordering |
| 3d | Increase chrono RRF beta for EVENT_ORDER | pg_recall.py | Incremental |

MRAG formula: final_score = semantic_score * temporal_score
6 constraint types: first/last x before/after/between
Floor=0.2 for constraint violations (from Figure 7)

Expected: event ordering 0.349 → 0.45-0.55

### Phase 4: Abstention — Separate project

See github.com/cdeust/cortex-abstention
Community-trained NLI model (MLX + ONNX)
Not blocking other improvements

## Constants Requiring Ablation

| Constant | Starting value | Source | Ablation range |
|---|---|---|---|
| Tag boost weight | 0.4 | Engineering default | [0.2, 0.4, 0.6, 0.8] |
| MMR lambda | 0.5 | Carbonell 1998 / LangChain default | [0.3, 0.5, 0.7] |
| Temporal floor | 0.2 | MRAG Figure 7 | [0.1, 0.2, 0.3] |
| Chrono RRF beta | 0.5 | Engineering default | [0.5, 0.7, 0.8] |
| Per-type min_slots | 2 | ENGRAM proportional (2/10) | [1, 2, 3] |
| Summarization pool multiplier | 2x | Engineering default | [2x, 3x] |

## Implementation Order

1. Phase 1 steps 1a+1b (prerequisites, no benchmark needed)
2. Phase 1 step 1c (tag boost) → benchmark
3. Phase 3 steps 3a+3b+3c (temporal anchor) → benchmark
4. Phase 1 steps 1d+1e (expansion + pool guarantee) → benchmark
5. Lambda/beta/floor ablation sweeps
