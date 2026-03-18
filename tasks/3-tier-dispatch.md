# 3-Tier Retrieval Dispatch

## Problem

One retrieval strategy doesn't fit all queries. Current smart dispatch only distinguishes simple vs multi-hop. BEAM shows instruction_following regresses with shared retriever (0.257 vs 0.513 inline). Each query type needs its best strategy.

## The Three Tiers

### Tier 1 — Simple (inline keyword + vector + temporal)
**When**: Single entity, short query, no conjunctions. Complexity score ≤ 0.3.
**Signals**: keyword overlap, vector similarity, temporal proximity, FlashRank reranking.
**Best for**: Single-hop recall, temporal queries, adversarial questions.
**Why**: Fast, precise, no noise from over-retrieval. LoCoMo single_hop 0.638, adversarial 0.766.

### Tier 2 — Mixed (multi-hop entity bridging)
**When**: Multiple entities, conjunction words, cross-session reasoning. Complexity score > 0.5.
**Signals**: Per-entity sub-queries, merged results, multi-hop boost, quality-gated stopping.
**Best for**: Multi-hop reasoning, cross-session evidence, relationship questions.
**Why**: Finds bridging entities across sessions. LoCoMo multi_hop 0.734.

### Tier 3 — Deep (BM25 + n-gram shared retriever)
**When**: Factual extraction, information-dense queries, instruction recall. High entity density + factual keywords.
**Signals**: Proper BM25 (k1=1.5, b=0.75), n-gram phrase matching, keyword overlap, FlashRank reranking.
**Best for**: Information extraction, instruction following, summarization queries.
**Why**: BM25 IDF weighting surfaces rare factual terms that keyword overlap misses. BEAM information_extraction 0.639.

## Dispatch Logic

```python
def dispatch(query: str) -> str:
    complexity = score_complexity(query)  # entity count, conjunctions, length
    factual = score_factual_density(query)  # entity density, question type

    if complexity > 0.5:
        return "mixed"      # multi-hop entity bridging
    if factual > 0.5:
        return "deep"       # BM25 + n-gram shared retriever
    return "simple"          # fast inline keyword + vector
```

### Factual Density Signals
- Named entity count > 2
- Question words: "what is", "list", "extract", "how many", "which"
- Instruction keywords: "rule", "constraint", "requirement", "must", "should"
- High proportion of capitalized/quoted terms

## Expected Impact

| Benchmark | Current | Expected | Why |
|---|---|---|---|
| LoCoMo MRR | 0.710 | 0.72+ | Better multi-hop dispatch |
| BEAM instruction | 0.257 | 0.45+ | Inline for instruction queries |
| BEAM extraction | 0.639 | 0.65+ | BM25+ngram for factual |
| BEAM overall | 0.353 | 0.40+ | Right strategy per ability |

## Implementation

1. Add `score_factual_density()` to `benchmarks/lib/scoring.py`
2. Update `LoCoMoRetriever._score_complexity()` to return tier name
3. Add `BenchmarkRetriever` as Tier 3 option in LoCoMo retriever
4. Add same dispatch to BEAM retriever
5. Quick test after each change: `bash benchmarks/quick_test.sh`
