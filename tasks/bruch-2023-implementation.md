# Bruch 2023 — Exact Implementation Spec

Paper: Bruch, Gai, Ingber. "An Analysis of Fusion Functions for Hybrid Retrieval." ACM TOIS 42(1), 2023. arXiv:2210.11934

## Exact Formula

```
s_hybrid = alpha * TMM(s_semantic) + (1 - alpha) * TMM(s_lexical)
```

## TMM Normalization (Theoretical Min-Max)

```
TMM(s) = (s - m_theoretical) / (M_query - m_theoretical)
```

Where:
- `m_theoretical` = theoretical minimum of the scoring function (NOT observed minimum)
- `M_query` = maximum score observed in current query's results (per-query)

### Theoretical minimums for PG signals:
- Vector (1 - cosine_distance): m_t = -1.0 (cosine range [-1, 1])
- FTS (ts_rank_cd): m_t = 0.0
- Trigram (similarity): m_t = 0.0
- Heat: m_t = 0.0
- Recency: m_t = 0.0

### Key difference from my failed implementation:
I used observed min-max (both bounds from data). Paper uses theoretical min + observed max.
This preserves absolute scale: a query where best cosine is 0.3 gets lower normalized score than one where best is 0.9.

## Alpha tuning
- Paper finds alpha should be tuned per domain on a small validation set
- Default alpha ~ 0.8 for semantic-primary retrieval
- For Cortex: use the existing weight parameters (p_w_vector, p_w_fts, etc.) AS the per-signal alphas
- Extension from 2-signal to 6-signal: weighted sum with per-signal TMM

## Implementation in PG stored procedure
Each signal CTE returns raw_score instead of rank. Then:
```sql
fused AS (
    SELECT id, SUM(contribution) AS fused_score FROM (
        SELECT v.id, p_w_vector * (v.raw_score - (-1.0)) / GREATEST(b.hi - (-1.0), 0.001) FROM vec v, vec_bounds b
        UNION ALL
        SELECT f.id, p_w_fts * f.raw_score / GREATEST(b.hi, 0.001) FROM fts f, fts_bounds b
        ...
    ) signals GROUP BY id
)
```

## Verification criteria
- Must match or exceed baseline WRRF scores on ALL 3 benchmarks
- Must run 3 consecutive identical results before claiming improvement
- If ANY benchmark regresses, revert

## Current baseline (WRRF, to match or beat):
- LME: R@10 97.8%, MRR 0.783
- LoCoMo: R@10 89.4%, MRR 0.605
- BEAM: 0.558

## Target (recorded best):
- LME: R@10 98.0%, MRR 0.880
- LoCoMo: R@10 97.7%, MRR 0.840
- BEAM: 0.627
