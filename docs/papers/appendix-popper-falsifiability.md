# Appendix: Falsifiability Audit (Popper Protocol)

**Companion to:** `thermodynamic-memory-vs-flat-importance.md`
**Method:** Each major claim is restated, paired with its riskiest prediction, the experiment that would refute it, and the current state of evidence. Claims are ordered by **severity-if-falsified**: a refutation of an earlier claim damages the paper's thesis more than a refutation of a later one.

A claim with no falsification condition is unscientific in Popper's sense and must not drive design decisions. Claims marked UNTESTED are conjectures, not results — the paper should label them as such.

---

## C3 — Lossless consolidation across long horizons (SEVERITY: critical)

**The claim.** "Cortex maintains lossless recall at any N because consolidation compresses episodic into semantic without loss."

**Riskiest prediction.** Across a 12-month timeline of 100k drip-fed memories, recall (R@10) of facts older than 9 months should not degrade by more than 5 percentage points relative to recall of facts under 1 month old.

**Falsification protocol.**
- N = 100,000 synthetic memories with timestamps spanning 12 months, ingested in temporal order through the production write path (predictive-coding gate, neuromodulation, synaptic tagging, decay cycle).
- Query set: 500 facts uniformly sampled across age buckets {<1mo, 1–3mo, 3–6mo, 6–9mo, >9mo}.
- Metric: R@10 per bucket.
- Threshold: if `R@10(>9mo) < R@10(<1mo) − 5pp`, the lossless claim is refuted and must be weakened to "graceful degradation with rate X."

**Current evidence.** **UNTESTED.** All three benchmarks (LongMemEval, LoCoMo, BEAM) are static snapshots ingested in one pass. There is no longitudinal drip-feed test. The "lossless" claim is currently a theoretical assertion about CLS (`dual_store_cls.py`) without empirical bound on compression error.

---

## C1 — Discriminability collapse of flat-importance retrieval at scale (SEVERITY: critical)

**The claim.** "As N → ∞, flat-importance retrieval discriminability collapses; Cortex's gap over flat-RAG grows with N."

**Riskiest prediction.** At fixed embedding model (sentence-transformers, 384D) and fixed query distribution, the R@10 gap (Cortex − flat-RAG) is **monotonically increasing** in N.

**Falsification protocol.**
- N ∈ {1k, 10k, 100k, 1M, 10M}, identical corpus and query set at each tier (the larger corpora are supersets).
- Two systems on the same PostgreSQL instance: (a) full Cortex pipeline; (b) flat-RAG control = vector + BM25 only, constant heat = 0.5, no decay, no WRRF heat term.
- Metric: R@10 gap = `R@10(Cortex) − R@10(flat)`.
- Threshold: if the gap is constant within ±2pp across the N-scan, or shrinks at any tier, the scaling claim is refuted. The paper would have to retreat to "advantage at small N" — a much weaker thesis.

**Current evidence.** **UNTESTED at the scaling level.** Each benchmark provides a single N-point: LongMemEval ≈ 500 memories per session, LoCoMo ≈ 600, BEAM at 100k. There is no N-scan with the same query distribution. The 100k point alone cannot establish a trend.

---

## C2 — Heat decay alone is sufficient to prevent collapse (SEVERITY: high)

**The claim.** "Heat decay alone (without the rest of the architecture) is sufficient to prevent retrieval discriminability collapse."

**Riskiest prediction.** Ablating only the decay (replace `decay_cycle.py` with constant heat = 0.5, leaving WRRF, predictive coding, neuromodulation, schemas, replay, etc. intact) drops R@10 by ≥ 80% of the full Cortex-vs-flat-RAG gap.

**Falsification protocol.**
- Use `mcp_server/core/ablation.py` to disable the decay mechanism only.
- Run on LongMemEval, LoCoMo, BEAM (current baselines).
- Metric: ΔR@10 = `R@10(full Cortex) − R@10(no-decay)`, normalized against `R@10(full) − R@10(flat-RAG)`.
- Threshold: if the no-decay ablation recovers ≥ 50% of the gap to flat-RAG (i.e., decay accounts for less than half the lift), the "decay alone is sufficient" claim is refuted. Some other mechanism (likely WRRF or pattern separation) is doing the work.

**Current evidence.** **UNTESTED.** 23 ablatable mechanisms are registered in `ablation.py`; no published row isolates "decay only" against the full system. The current per-mechanism ablation log in `tasks/benchmarks-detail.md` does not cover this ablation.

---

## C5 — 97.8% LongMemEval R@10 generalizes beyond the benchmark (SEVERITY: high)

**The claim.** "97.8% LongMemEval R@10 generalizes beyond the benchmark — the system is not overfit."

**Riskiest prediction.** Calibration parameters tuned on LongMemEval (WRRF weights, intent classifier thresholds, FlashRank reranker depth) transfer to LoCoMo without retuning, retaining ≥ 90% of LongMemEval's R@10 (i.e., LoCoMo R@10 ≥ 0.88).

**Falsification protocol.**
- Freeze all hyperparameters at their LongMemEval-tuned values.
- Evaluate on LoCoMo (1986 Qs) and BEAM (200 Qs at 100k) without modification.
- Metric: R@10 on each held-out benchmark.
- Threshold: if frozen LongMemEval calibration yields LoCoMo R@10 < 0.83 or BEAM Overall < 0.45, the cross-benchmark generalization claim is refuted.

**Current evidence.** **PARTIALLY TESTED.** Each benchmark is currently scored independently with whatever defaults exist at the time, but the calibration history is not version-pinned to a single benchmark. Current scores (LongMemEval 97.8%, LoCoMo 92.6%, BEAM 0.543) are *consistent with* generalization but do not prove it: per-benchmark drift in defaults could be hiding overfitting. A frozen-config cross-eval has not been run.

---

## C4 — WRRF fusion of 6 signals decorrelates noise sources (SEVERITY: medium)

**The claim.** "WRRF fusion of 6 signals (vector, FTS, trigram, heat, recency, intent) decorrelates noise sources."

**Riskiest prediction.** (a) The 6×6 signal-correlation matrix on retrieval scores has off-diagonal magnitudes < 0.3. (b) Ablating any single signal drops R@10 by ≤ 2pp on each benchmark.

**Falsification protocol.**
- For (a): on a held-out 1000-query sample, log per-signal scores before fusion; compute Pearson correlation matrix.
- For (b): six ablations via `ablation.py`, one per signal; measure ΔR@10 on LongMemEval, LoCoMo, BEAM.
- Threshold: if any off-diagonal exceeds 0.5, OR any single-signal ablation drops R@10 by > 5pp, the "decorrelated noise" claim is refuted — at least one signal is load-bearing rather than complementary.

**Current evidence.** **PARTIALLY TESTED.** `tasks/benchmarks-detail.md` records ablations for some signals (vector, FTS) but not all six. The signal-correlation matrix has not been computed. The decorrelation claim is currently a design rationale, not a measurement.

---

## C6 — Per-write cost is justified by read/write ratio (SEVERITY: low — but easy to test)

**The claim.** "Per-write cost (predictive coding + neuromodulation + synaptic tagging) is justified by 100× more frequent reads."

**Riskiest prediction.** The empirical read/write ratio in production usage is ≥ 50:1.

**Falsification protocol.**
- Instrument `pg_recall.py` and `write_gate.py` with counters.
- Log every read and write for one calendar week of normal usage.
- Metric: `reads / writes`.
- Threshold: if ratio < 20:1, the cost-amortization argument fails; the per-write expense is not earned and the architecture should expose a "write-light" mode.

**Current evidence.** **UNTESTED.** The 100:1 figure is asserted, not measured. Counters are not currently logged.

---

## Summary table

| Claim | Severity-if-falsified | State | Single experiment that resolves it |
|---|---|---|---|
| C3 lossless across time | critical | UNTESTED | 12-month drip-feed longitudinal benchmark |
| C1 scaling gap grows | critical | UNTESTED | N-scan {1k…10M} with shared query set |
| C2 decay alone suffices | high | UNTESTED | Single ablation row in `ablation.py` |
| C5 cross-benchmark generalization | high | PARTIALLY TESTED | Frozen-config cross-eval |
| C4 WRRF decorrelates | medium | PARTIALLY TESTED | Correlation matrix + 6 ablations |
| C6 read/write 100:1 | low | UNTESTED | One week of production counters |

No claim in the paper is currently CONFIRMED in the strict Popperian sense (survived a severe test designed to refute it). The 97.8% / 92.6% / 0.543 numbers are corroborations of the system as configured, not corroborations of the causal claims (C1–C6) about *why* it performs.

---

## What evidence is missing

To convert this paper from a defensible-but-narrowly-evidenced position into a strong empirical claim, the Limitations section should acknowledge — and the next experimental cycle should produce — the following: (i) an **N-scan** at fixed query distribution from 1k to 10M proving that the Cortex-vs-flat gap grows monotonically (resolves C1); (ii) a **longitudinal drip-feed benchmark** with synthetic 12-month timestamps showing bounded degradation of old-fact recall (resolves C3, the most fragile claim); (iii) a **decay-only ablation row** isolating heat decay from the other 22 mechanisms (resolves C2 — and may surprise the authors by attributing the lift elsewhere); (iv) a **frozen-config cross-benchmark evaluation** with hyperparameters pinned to their LongMemEval-tuned values (resolves C5); (v) a **6×6 signal correlation matrix plus per-signal ablations** to substantiate the decorrelation claim quantitatively (resolves C4); and (vi) one week of **production read/write telemetry** to verify the 100:1 amortization assumption (resolves C6). Without (i) and (iii) in particular, the central thesis — that *thermodynamic decay specifically* prevents discriminability collapse — remains a plausible hypothesis rather than a tested result. The current benchmark scores are consistent with the thesis but also consistent with several alternative explanations (WRRF doing the work, pattern separation doing the work, or simply better embedding-side retrieval at the tested N), and a paper that does not run the experiments to discriminate among these alternatives is, in Popper's terms, displaying corroborations rather than risking refutations.
