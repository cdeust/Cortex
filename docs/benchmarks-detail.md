<summary>Ablation log — approaches tried and results</summary>

**Emotional memory processing (BEAM +0.038 MRR, shipped)**

| Change | Paper | Result |
|---|---|---|
| Emotional retrieval signal (time-dependent multiplicative boost) | Yonelinas & Ritchey 2015 | +0.035 MRR, +5.1pp R@10 |
| Time-dependent decay resistance | Yonelinas & Ritchey 2015 | Included in above |
| Reconsolidation emotional boost + PE gate + age factor | Lee 2009, Osan-Tort-Amaral 2011, Milekic & Alberini 2002 | Included in above |

**Event ordering + summarization intent (BEAM +0.003 MRR, shipped)**

| Change | Paper | Result |
|---|---|---|
| EVENT_ORDER intent + chronological RRF reranking | ChronoRAG (Chen 2025), Cormack et al. (SIGIR 2009) | event_ordering 0.339→0.349 |
| SUMMARIZATION intent detection | — | summarization 0.379→0.391 |

**MMR diversity reranking (no improvement, disabled)**

| Lambda | Summarization MRR | Overall MRR | Verdict |
|---|---|---|---|
| No MMR | **0.391** | **0.543** | Baseline |
| 0.5 | 0.367 | 0.540 | Regression |
| 0.7 | 0.381 | 0.538 | Regression |

MMR (Carbonell & Goldstein, SIGIR 1998) trades precision for coverage. BEAM's MRR metric rewards first-hit position, so any diversity reranking hurts. Module kept (`mmr_diversity.py`) for future QA-based evaluation.

**Instruction/preference typed retrieval (no improvement, stashed)**

Six approaches tried to improve instruction_following (0.244) and preference_following (0.374):

| Approach | Paper | Instruction | Preference | Overall | Verdict |
|---|---|---|---|---|---|
| Baseline (no type work) | — | 0.244 | 0.374 | 0.543 | — |
| Tag boost in PL/pgSQL (weight 0.4) | ENGRAM | 0.245 | 0.370 | 0.540 | No help |
| Tightened regex + gated type pool | ENGRAM, Searle 1969 | **0.245** | **0.390** | **0.546** | Best |
| Centroid classifier (Snell 2017) + gated pool | Prototypical Networks | 0.241 | 0.357 | 0.544 | Slight regression |
| Centroid ungated + insert at rank 1 | ENGRAM | 0.203 | 0.295 | 0.434 | **Destructive** |
| Centroid ungated + append | ENGRAM | 0.241 | 0.372 | 0.545 | Neutral |
| Centroid ungated + pre-rerank inject | ENGRAM | 0.241 | 0.375 | 0.544 | Neutral |

**Root cause analysis:** BEAM instruction/preference queries look like normal questions ("Could you show me how to implement a login feature?") — not instruction-seeking queries. Intent classification cannot detect them because there's no instruction signal in the query. The answer should come from a stored instruction memory that is semantically close to the topic, but the standard WRRF retrieval already finds those memories — they just don't rank higher than episodic memories about the same topic. The problem is not recall (memories are found) but discrimination (instruction memories are indistinguishable from episodic memories by embedding similarity alone).

**Open problem:** Instruction/preference retrieval requires either (a) a query-side classifier that detects "this question would benefit from instruction context" without keyword signals, or (b) a fundamentally different approach like ENGRAM's LLM-based routing at ingestion time. See [cortex-abstention](https://github.com/cdeust/cortex-abstention) for the community-driven model approach.

</details>
