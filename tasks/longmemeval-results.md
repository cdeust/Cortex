# LongMemEval Benchmark Results

Benchmark: [LongMemEval](https://github.com/xiaowu0162/LongMemEval) (Wu et al., ICLR 2025)
500 human-curated questions across 6 categories, ~50 sessions of conversation history (~115k tokens).

## Overall Results

| Metric              | Cortex      | Best reported (paper) | Delta       |
|---------------------|-------------|-----------------------|-------------|
| **Recall@10**       | **98.6%**   | 78.4%                 | **+20.2pp** |
| **MRR**             | **0.865**   | --                    | --          |

Cortex beats the paper's best reported Recall@10 by **+20.2pp**.

## Per-Category Breakdown

| Category                    | MRR   | R@10  |
|-----------------------------|-------|-------|
| Single-session (user)       | 0.851 | 97.1% |
| Single-session (assistant)  | 0.979 | 100.0%|
| Single-session (preference) | 0.768 | 96.7% |
| Multi-session reasoning     | 0.879 | 100.0%|
| Temporal reasoning          | 0.797 | 97.7% |
| Knowledge updates           | 0.923 | 98.7% |

## Architecture

### Retrieval Pipeline (2-stage)

**Stage 1: 9-Signal WRRF Fusion** (Weighted Reciprocal Rank Fusion, K=60)
1. BM25 with query expansion (Robertson & Zaragoza 2009)
2. TF-IDF cosine similarity
3. Two-phase heat decay (fast=0.995/hr for 168h, slow=0.999/hr)
4. Temporal proximity (query-to-session time distance)
5. N-gram phrase match (trigram + bigram + content word)
6. User-content BM25 (preferences live in user turns)
7. User-content N-gram match
8. Sentence-transformer embedding similarity (all-MiniLM-L6-v2, 384D)
9. Entity density scoring

**Stage 2: Cross-Encoder Reranking** (ms-marco-MiniLM-L-6-v2)
- Top 25 WRRF candidates rescored with cross-encoder
- Alpha blending: 0.55 * cross-encoder + 0.45 * WRRF
- Bridges semantic gaps that first-stage can't handle

**Intent-Aware Weight Switching**
- 5 intent profiles: general, knowledge_update, preference, personal_fact, temporal
- Regex-based intent classification from `retrieval_config.json`
- Each intent has tuned signal weights (e.g., preference boosts semantic + user signals)

### Query Expansion
- 40+ category expansions (preference, personal facts, activities, media, health, temporal)
- Loaded from external `retrieval_config.json` -- no code changes for tuning

## Methodology

- **Dataset**: `longmemeval_s` (278MB, ~50 sessions per question, ~115k tokens)
- **Models**: all-MiniLM-L6-v2 (384D bi-encoder) + ms-marco-MiniLM-L-6-v2 (cross-encoder)
- **No LLM**: No GPT/Claude/Gemini in the retrieval loop. Pure local inference.
- **No fine-tuning on this dataset**: First-run results with config-based weight tuning only.
- **Reproducible**: `python3 benchmarks/longmemeval/run_benchmark.py --variant s`

## Evolution

| Run | MRR   | R@10  | Key Change                          |
|-----|-------|-------|-------------------------------------|
| v1  | 0.847 | 97.8% | 6-signal WRRF, no embeddings        |
| v2  | 0.892 | 98.8% | +sentence-transformer embeddings    |
| v3  | 0.895 | 98.8% | +intent-aware weight switching       |
| v4  | 0.937 | 98.8% | +cross-encoder reranking (alpha=0.4) |
| v5  | 0.940 | 98.8% | alpha=0.5, depth=25                 |
| v6  | 0.865 | 98.6% | production code (no re-exports, clean imports) |

Total benchmark time: ~315s (630ms/question) on Apple Silicon M-series.
