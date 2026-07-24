# LongMemEval-S · SQLite three-way — issue #169 zero-download semantic fallback

Harness: `benchmarks/longmemeval/run_sqlite_fallback_bench.py`
(a #169-specific harness — the production `run_benchmark.py` drives PostgreSQL +
pgvector and has no no-vector / embedding-mode toggle, so it cannot express this
three-way SQLite comparison. This harness reuses the production harness's
dataset loading + scoring functions verbatim: `session_to_memory_content`,
`parse_longmemeval_date`, `compute_heat_with_decay`, `compute_mrr`,
`recall_at_k_binary`.)

- Dataset: `longmemeval_s.json` (Wu et al., ICLR 2025), variant `s`.
- Branch: `feat/semantic-fallback-169` (tree state as committed in this PR).
- Base sha at run time: `ecdbadc` (run from the working tree before the commit;
  no code under test changed between the run and the commit).
- Date: 2026-07-24 (UTC).
- Bounded run: `--limit 50` questions. Full floors are NOT required — the
  PostgreSQL / sentence-transformers production path is untouched by #169; this
  measures only the SQLite fallback path #169 introduces.
- Environment: CPU, macOS dev host, in-memory `SqliteMemoryStore` per question
  (`:memory:`), zero network for the no-vector and fallback modes.

## Results (n = 50)

| mode                    |   MRR | Recall@10 | elapsed |
|-------------------------|------:|----------:|--------:|
| (a) no-vector baseline  | 0.275 |     46.0% |   5.1 s |
| (b) algorithmic fallback| 0.378 |     66.0% |  36.0 s |
| (c) sentence-transformers | 0.609 |   94.0% |  44.1 s |

Fallback vs no-vector: **ΔMRR = +0.102, ΔRecall@10 = +20.0 pp** →
**fallback BEATS the no-vector baseline** (issue #169 adoption criterion met).

A confirming n = 20 run gave the same ordering (fallback ΔMRR +0.137,
ΔR@10 +25.0 pp).

## Reading

The fallback lands where a download-free approximation should: materially above
the no-vector floor (it recovers half the gap to the neural encoder on MRR and
~40% of it on Recall@10), and clearly below the neural model — which is why the
two spaces are kept from cross-ranking and why re-embedding upgrades a store
transparently once the model arrives.

Reproduce:

```
python3 benchmarks/longmemeval/run_sqlite_fallback_bench.py --limit 50 \
    --results-out benchmarks/results/semantic-fallback-169/lme-s-sqlite-3way.json
```
