# Verification Protocol — Pre-Registration (Popper-Falsifiability Campaign)

**Author:** experiment-runner
**Frozen at:** TBD (commit SHA at protocol freeze)
**Companion:** `docs/papers/appendix-popper-falsifiability.md`
**Status:** PRE-REGISTERED. Modifications after freeze require an addendum, not an edit.

This protocol covers six experiments (E1–E6) that resolve falsifiability claims C1–C6.
All confirmatory analyses below are pre-registered; any analysis added after seeing data
must be labelled exploratory and reported separately.

---

## Global invariants (apply to all experiments)

- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2`, 384-dim. Pinned via lockfile.
- **DB:** PostgreSQL 15+ with pgvector, pg_trgm. Single instance, single process per run.
- **Hyperparameters:** Frozen at the values present at the protocol-freeze commit. No
  per-experiment tuning unless the experiment IS the tuning sweep (E3 only).
- **Embedding cache:** Pre-computed once on the union of all corpora. SHA-256 of cache file
  recorded in every manifest. No on-the-fly embedding during scored runs.
- **Determinism:** `PYTHONHASHSEED=0`, `numpy.random.default_rng(seed=...)`, FlashRank ONNX
  in deterministic mode. No GPU; CPU-only (`CUDA_VISIBLE_DEVICES=""`).
- **Clean DB protocol:** Every scored run starts with `pg_schema.recreate()` then loads only
  the corpus for that run. No carry-over.
- **Manifest sidecar (mandatory per run):** `code_hash`, dirty-flag (must be clean for
  scored rows), `data_hash` (SHA-256 of corpus manifest), seeds (numpy + run ordering),
  `embedding_cache_sha`, `package_lockfile_sha`, hardware (`uname -a`, RAM, CPU), wall-clock,
  exact CLI command, `stopping_reason`. Missing field → row downgraded to exploratory.
- **Read/write isolation during ablation:** E1 runs MUST disable any write path that fires
  during recall (telemetry from E6 is the gating evidence — see ordering).

---

## E1 — Per-mechanism ablation (resolves C2 + extends C4)

**Hypothesis (confirmatory).** For at least one mechanism M ∈ Mechanism, disabling M
yields ΔR@10 ≤ −2.0 pp on at least one of {LongMemEval-S, LoCoMo, BEAM} relative to
the full-system baseline. Specifically, for **decay** (`ADAPTIVE_DECAY` + decay path
in `decay_cycle.py`): predicted ΔR@10 on BEAM ≤ −10 pp (the C2 claim that decay alone
carries ≥80% of the lift implies a large isolated decay effect).

**Falsification.** If ΔR@10(decay-off, BEAM) > −5 pp, C2 ("decay is sufficient") is refuted
and the lift attribution must move to another mechanism (likely WRRF or pattern separation).

**Design.**
- Factors: 1 (Mechanism). Levels: 26 enum values from `Mechanism` + 1 baseline = 27 cells
  per benchmark × 3 benchmarks = **81 cells**.
- Replications per cell: **3 seeds** (numpy + DB load order). Total runs: 243.
- Zero-cell (anchor): full system, no mechanism disabled. Run **first** on each benchmark.
- Blocking: same hardware, same embedding cache, same Postgres binary version per benchmark
  block. Benchmarks run sequentially (E1-LongMemEval, then E1-LoCoMo, then E1-BEAM) to
  isolate bench-specific drift.
- Randomization: order of (mechanism × seed) pairs within each benchmark block is
  randomized via `numpy.random.default_rng(seed=20260428)`.

**Sample size / power.**
- Benchmarks fixed: LongMemEval-S = 500 Q, LoCoMo = 1986 Q, BEAM = 200 Q.
- Per-question outcome is binary (R@10 ∈ {0,1}); paired across baseline vs ablation on
  the SAME question.
- McNemar's exact test on the discordant pairs. With 200 Q (BEAM, smallest) and a
  predicted shift of 10 pp, expected discordant cells ≈ 30; exact one-sided power ≥ 0.95
  for α = 0.05 / 26 (Bonferroni) when true shift ≥ 8 pp. Smaller effects underpowered
  on BEAM and reported as "not detectable at this N."

**Primary metric + threshold.** ΔR@10 vs baseline, per benchmark per mechanism.
Pass for the C2 sub-hypothesis = ΔR@10(decay-off, BEAM) ≤ −10 pp AND McNemar p < 0.05/26.

**Secondary metrics.** ΔMRR; per-category R@10 (LongMemEval); ΔR@10 on the other two
benchmarks; impact_score from `core.ablation.compute_impact_score`.

**Pre-registered analysis.** McNemar's exact test per (benchmark × mechanism); paired
bootstrap 95% CI on ΔR@10 (10 000 resamples, seed pinned). Bonferroni correction across
the 26 mechanisms within each benchmark (α_family = 0.05 → α_test = 0.0019). Cross-
benchmark replication is descriptive only — no further correction needed.

**Stopping rule.** All 243 runs complete OR cumulative wall-clock exceeds 10× the median
single-run wall-clock × 243, whichever first. On budget exhaustion, report partial table
labelled "incomplete; halted by stopping rule" and the negative-log entry for each
non-run cell.

**Reproducibility manifest** (in addition to global): per row, the
`AblationConfig.disabled` set serialized as a sorted JSON array.

**Exact command (template).**
```
PYTHONHASHSEED=0 CUDA_VISIBLE_DEVICES="" \
python3 benchmarks/<bench>/run_benchmark.py \
  --ablation '{"disabled":["<mechanism_value>"]}' \
  --seed <s> --variant s --emit-manifest results/E1/<bench>/<mech>/<seed>.json
```

**Consolidation-only mechanism ablation requires `--with-consolidation`.**
Nine mechanisms are wired into the production write/maintenance path but never
exercised by the LME-S harness in its default mode (corpus load → recall, no
`consolidate()` call): CASCADE, INTERFERENCE, HOMEOSTATIC_PLASTICITY,
SYNAPTIC_PLASTICITY, MICROGLIAL_PRUNING, TWO_STAGE_MODEL, EMOTIONAL_DECAY,
TRIPARTITE_SYNAPSE, SCHEMA_ENGINE. Ablating any of them in default mode
yields ΔMRR ≈ +0.000, which is a benchmark-coverage artifact, not evidence
that the mechanism is inert. For E1 v3 these nine rows on LongMemEval-S
MUST be run with `--with-consolidation --ablate <MECH>`; the harness exports
`CORTEX_ABLATE_<MECH>=1` BEFORE the consolidation pass and the recall loop,
so the ablation guard fires inside the affected stage and the rest of the
consolidation pipeline still runs. Wall time of the consolidation pass is
recorded separately in the result manifest (`consolidation_total_wall_s`,
`consolidation_call_count`) and is NOT charged against per-question
latency. Default mode (no flag) preserves historical run reproducibility
unchanged.

```
# E1 v3 row for a consolidation-only mechanism on LME-S:
PYTHONHASHSEED=0 CUDA_VISIBLE_DEVICES="" \
uv run python benchmarks/longmemeval/run_benchmark.py \
  --variant s --with-consolidation --ablate CASCADE \
  --results-out results/E1v3/lme-s/CASCADE/<seed>.json
```

---

## E2 — N-scan curve (resolves C1)

**Status (post-pre-registration revision).** Initial E2 design used a synthetic
corpus generator at varying N. Empirical finding (see
`benchmarks/results/latency_benchmark/20260430T201246Z_pre_wire/` and
`20260430T204157Z/`): cortex_full and cortex_flat produced **identical** R@10
and MRR at N≥10k because the synthetic corpus carries no thermodynamic
structure for heat to discriminate. The original synthetic harness has been
repurposed as the **latency-only** benchmark (`benchmarks/lib/latency_runner.py`,
results under `benchmarks/results/latency_benchmark/`); its retrieval scores
are not claim-bearing.

The E2 retrieval claim is now resolved by **two complementary runners**:
**E2a** (real-benchmark subsampling — primary) and **E2b** (Zipf synthetic —
extension past 1M). The original hypothesis below stands; the design is
re-pointed at these runners.

### E2a — Real-benchmark subsampling (primary)

**Runner.** `benchmarks/lib/e2_subsample_runner.py`.

**Hypothesis (confirmatory).** The MRR gap (cortex_full − cortex_flat) is
non-decreasing in N when subsampling each of {LongMemEval-S, LoCoMo,
BEAM-100K} from a small prefix up to the benchmark's full corpus, with at
least one consecutive (10×) tier showing a ≥1.0 pp strict increase.

**Falsification.** The gap between cortex_full and cortex_flat MRR on every
one of {LongMemEval-S, LoCoMo, BEAM-100K} at N=full is < 5 pp → the
thermodynamic-structure-matters claim is refuted; paper drops C1 in its
present form.

**Design.**
- Factors: 3 (benchmark) × 2 (condition: cortex_full / cortex_flat) ×
  ≥4 (N tiers per benchmark, ramp 10× until full).
- Subsampling: deterministic seed-stable shuffle, then prefix-of-length-N.
  Probes filtered to those whose target source keys remain in the subsample,
  then `--queries` of them sampled (seed-stable).
- Conditions toggled via `benchmarks/lib/_e2_conditions.py` (cortex_flat sets
  `CORTEX_DECAY_DISABLED=1`, `CORTEX_HEAT_CONSTANT=0.5`,
  `CORTEX_CONSOLIDATION_DISABLED=1`; loaded memories forced to heat=0.5).
- Production write/read paths exercised via `BenchmarkDB` — same code as the
  standalone benchmark runners.

**Stopping rule.** Per-benchmark, halts at 12h wall-clock OR full N reached.

**Reproducibility manifest.** seed, schema_version (1), embedding_model,
embedding_dim, n_queries actually scored, condition, N. One JSON per
(benchmark, N, condition) plus `summary.csv` per timestamped run.

### E2b — Zipfian synthetic corpus (extension)

**Runner.** `benchmarks/lib/e2_zipf_runner.py`.

**Hypothesis (confirmatory).** Adding the Zipfian access pattern produces
the missing thermodynamic structure: at N ∈ {10⁵, 10⁶, 10⁷}, MRR gap
(cortex_full − cortex_flat) ≥ 5 pp.

**Falsification.** Even with explicit Zipf(α=1.5) access pattern routed through
the production write-back-on-recall, no detectable gap → the thermodynamic
account does not generalize past native benchmarks; demote E2b to descriptive.

**Design.**
- Synthetic corpus: N memories across 50 topic clusters (semantic continuity
  within topic so embeddings cluster).
- K access events drawn from Zipf(α). Each access invokes `db.recall()` —
  heat-update is performed by the production write-back hook (no direct
  heat assignment).
  - source: Zipf, G. K. (1949). *Human Behavior and the Principle of Least
    Effort.* Addison-Wesley.
  - source: Mandelbrot, B. (1953). *An Informational Theory of the
    Statistical Structure of Language.* α=1.5 is the natural-language
    empirical default.
- Queries biased toward high-access topics (drawn from same Zipf
  distribution).
- Conditions identical to E2a via `_e2_conditions.py`.

**Stopping rule.** Per N tier halts at 12h OR completion. The 10⁷ tier is
**stretch**; report partial results if budget exhausts.

**Reproducibility manifest.** seed, schema_version (1), zipf_alpha,
access_events, n_queries, condition, N. One JSON per (N, condition) plus
`summary.csv` per timestamped run.

### E2-latency — Synthetic-corpus latency sibling

**Runner.** `benchmarks/lib/latency_runner.py` (retains import alias
`benchmarks.lib.n_scan_runner` for in-flight callers).

**Status.** **NOT** claim-bearing for retrieval. Only `wall_per_query_ms` and
`rss_peak_mb` from this runner inform paper claims. Its R@1 / R@10 / MRR
fields are written to the JSON for parity with the other runners but
explicitly disclaimed by the `latency_only: true` field in each result and
by the stderr banner emitted at startup.

**Design.** Same synthetic generator as the original E2 harness; same conditions
(cortex_full / cortex_flat) so latency under both is recorded; results live
under `benchmarks/results/latency_benchmark/`.

---

## E3 — Decay dose-response (resolves "constants are calibrated, not derived")

**Hypothesis (confirmatory).** R@10 on BEAM as a function of `decay_factor`
(`thermodynamics.compute_decay`, default 0.95) has a non-monotonic optimum strictly
inside the swept interval [0.85, 1.00], i.e. R@10(λ*) > R@10(0.85) AND R@10(λ*) > R@10(1.00)
for some λ* ∈ {0.85, 0.90, 0.95, 0.98, 0.99}.

**Falsification.** If R@10 is monotone in λ across the sweep, "calibration" is
indistinguishable from "no-decay-is-best" or "max-decay-is-best" and the constant
0.95 is unjustified — paper must drop the calibration claim.

**Design.**
- Factor: λ_base ∈ {0.85, 0.90, 0.95, 0.98, 0.99, 1.00}. Levels: 6.
- Replications: **5 seeds** per λ (BEAM is 200 Q — needs more reps for stable variance).
- Zero-cell: λ = 1.00 (no decay). Run first.
- Blocking: same hardware, same embedding cache, same Postgres state per run (clean DB
  reload between λ values to remove leakage from prior heat trajectories).
- Randomization: λ × seed execution order randomized (seed=20260428).
- IMPORTANT: `importance_decay_factor` (0.998) and `emotional_decay_resistance` (0.5) are
  held FIXED at their committed defaults. Sweeping more than one constant at once is a
  separate experiment and out of scope here.

**Sample size / power.** 200 Q × 5 seeds = 1000 question-evaluations per λ. Paired
across λ on the same question-seed pair. Detectable ΔR@10 at α=0.05/5 (Bonferroni
across 5 non-baseline λ values) ≈ 3 pp.

**Primary metric.** R@10(λ) on BEAM. Pass = at least one interior λ beats both
endpoints (λ=0.85 and λ=1.00) by ≥ 3 pp AND McNemar p < 0.05/5 vs each endpoint.

**Secondary metrics.** Local sensitivity = max R@10 minus second-best R@10 (small =
flat optimum, robust calibration; large = knife-edge, suspicious). MRR curve;
per-BEAM-category R@10 curves.

**Pre-registered analysis.** Per-λ paired McNemar vs λ=1.00; bootstrap 95% CI per λ
(10 000 resamples); Bonferroni across 5 comparisons. Optimum location reported with
its bootstrap CI; sensitivity reported as a single number.

**Stopping rule.** All 30 runs complete OR 8h wall-clock total, whichever first.

**Reproducibility manifest:** patch diff for `compute_decay`'s `decay_factor` per row.

---

## E4 — Longitudinal lossless-recall (resolves C3, the most fragile claim)

**Hypothesis (confirmatory).** After drip-feeding 100 000 synthetic memories with
timestamps spanning 12 months through the production write path, R@10 by query age
bucket satisfies: R@10(>9mo) ≥ R@10(<1mo) − 5 pp.

**Falsification.** R@10(>9mo) < R@10(<1mo) − 5 pp → C3 ("lossless across time") is
refuted. Paper must weaken to "graceful degradation at rate X pp/month."

**Design.**
- Factor: query age bucket ∈ {<1mo, 1-3mo, 3-6mo, 6-9mo, 9-12mo}. Levels: 5.
- Single system: full Cortex (no comparison arm; this is an absolute-property test).
- Replications: 3 independent corpus generations (seeds 0,1,2). 100 queries per age
  bucket per seed = 500 queries × 3 seeds = 1500 total queries.
- Zero-cell: <1mo bucket (anchor for "newest-fact recall ceiling").
- Drip-feed protocol: memories written one at a time via `remember()` in temporal
  order, with simulated `created_at` advancing through the year. Decay clock advances
  monotonically — NO time-skipping shortcuts; all consolidation cycles fire at their
  natural cadence.
- Blocking: same hardware, embedding cache, Postgres binary. Seeds run sequentially.
- Randomization: per seed, order of facts within a single calendar day is shuffled.

**Sample size / power.** 300 Q per age bucket (across 3 seeds). Paired comparison
{<1mo} vs {>9mo} on matched corpora. McNemar exact, α=0.05; detectable shift ≥ 4 pp
at power 0.90.

**Primary metric.** R@10(>9mo) − R@10(<1mo). Pass = ≥ −5 pp AND McNemar p < 0.05
(against the null "drop is exactly 0").

**Secondary.** R@10 per bucket (full curve); MRR per bucket; recall as function of
age in days (continuous, fitted with isotonic regression — exploratory).

**Pre-registered analysis.** McNemar exact on the {<1mo} vs {>9mo} pair; bootstrap
95% CI per bucket (10 000 resamples). No correction across buckets — only one
confirmatory comparison.

**Stopping rule.** All 3 seeds complete OR 36h total wall-clock (drip-feed dominates).
Per-seed checkpoint every 10k memories so a kill leaves recoverable state.

**Reproducibility manifest:** drip-feed schedule (calendar day → memory count), seed,
SHA-256 of generated corpus.

---

## E5 — Cross-benchmark generalization (resolves C5)

**Hypothesis (confirmatory).** With ALL hyperparameters frozen at their LongMemEval-tuned
values (committed at protocol freeze, hashed), LoCoMo MRR is within 0.08 of its
standalone-tuned MRR (currently 0.794). I.e., MRR(LoCoMo, frozen-config) ≥ 0.714.

**Falsification.** MRR(LoCoMo, frozen) < 0.714 → C5 refuted. The 97.8% LongMemEval is
a calibration artefact, not a generalizable result.

**Design.**
- Factor: configuration source ∈ {LongMemEval-tuned (frozen)}. No tuning loop on LoCoMo.
- Single arm; the comparator is the historical LoCoMo standalone-tuned score from
  CLAUDE.md (MRR=0.794). This is a one-arm pre-registered claim.
- Replications: 3 seeds (DB load order). LoCoMo is 1986 Q — high statistical power.
- Zero-cell: prior published MRR=0.794 (read from `tasks/benchmarks-detail.md` snapshot
  at protocol freeze).
- Blocking: same hardware, embedding cache, Postgres binary as E1's LoCoMo block.

**Sample size / power.** 1986 Q × 3 seeds = 5958 evaluations. Paired bootstrap on MRR.
Detectable shift ≥ 0.01 MRR at power 0.95.

**Primary metric.** MRR(LoCoMo, frozen-config), averaged over 3 seeds. Pass = ≥ 0.714
AND bootstrap 95% lower bound ≥ 0.700.

**Secondary.** R@10(LoCoMo, frozen); per-category MRR; same evaluation on BEAM
(MRR ≥ 0.45 absolute) — descriptive only.

**Pre-registered analysis.** Bootstrap 95% CI on MRR (10 000 resamples). One-sample
test against the threshold 0.714 (one-sided, α=0.05). No multiple-comparison
correction (single confirmatory test).

**Stopping rule.** 3 seeds complete OR 6h wall-clock.

**Reproducibility manifest:** SHA-256 of the frozen config file; commit SHA at freeze.

---

## E6 — Read/write ratio (resolves C6, gates E1)

**Hypothesis (confirmatory).** Empirical reads-to-writes ratio over a 7-calendar-day
production telemetry window is ≥ 50:1.

**Falsification.** Ratio < 20:1 → C6 refuted; per-write cost is not amortized.

**Design.**
- Instrumentation (separate agent owns the implementation): atomic counters in
  `mcp_server/infrastructure/pg_recall.py::recall_memories()` (read counter) and
  `mcp_server/handlers/remember.py` → `core/write_gate.py` write path (write counter).
  Counters persisted to PG table `telemetry_counters(date, reads, writes)`.
- No factors, no replications — this is an observational telemetry study.
- Window: contiguous 7×24h starting at telemetry-deploy commit.
- Confound block: only Clément's primary workstation counted (single-user environment);
  benchmark runs are EXCLUDED via a `caller_tag != "benchmark"` filter at counter site.
  This filter is **load-bearing** for E1: ablation runs must not contaminate the ratio.

**Sample size / power.** Observational; N is whatever the week produces. If reads < 100
in the window, declare "underpowered, ratio undetermined" and extend by 7 more days
(pre-registered extension; max 21 days).

**Primary metric.** `total_reads / total_writes` over the window. Pass = ≥ 50:1.

**Secondary.** Daily ratio (drift detection); reads-per-hour distribution; writes that
were rejected by the predictive-coding gate (denominator-only count).

**Pre-registered analysis.** Wilson 95% CI on the ratio (treating each event as
Bernoulli read-vs-write). Report point estimate + CI; no significance test.

**Stopping rule.** 7 days elapsed (or 14, or 21 per extension rule above) OR total
event count ≥ 10 000, whichever first.

**Reproducibility manifest:** telemetry table dump (CSV), commit SHA of the
instrumentation, schema migration SHA.

---

## Negative-result log policy

Every cell that does not support its hypothesis gets an entry in
`tasks/negative-results-log.md` with: hypothesis, design pointer, manifest hash,
result, candidate explanation. No quiet reframing. No rerun-until-positive.

---

## Execution order (Gantt)

```
Day 0           : Freeze protocol commit. Compute embedding cache (one-shot).
Day 0  → Day 1  : E6 instrumentation deploys (separate agent).
Day 0  → Day 7  : E6 telemetry window runs PASSIVELY (no benchmark traffic).
                  E1, E2, E3, E4, E5 are BLOCKED until Day 7 ends OR a
                  `caller_tag` exclusion is verified to keep E6 clean.

Day 7           : E6 result computed. Two paths:
                  - Ratio ≥ 50:1 → C6 holds, proceed.
                  - Ratio < 20:1 → C6 refuted; E1 still runs but the cost-amortization
                    framing is dropped from the paper.

Day 7+ (parallel where compute allows; sequential as listed if single-machine):
  Lane A (CPU-bound, sequential per benchmark):
    E1-LongMemEval (≈ 27 cells × 3 seeds, ~6h)
    E1-LoCoMo      (≈ 27 cells × 3 seeds, ~12h)
    E1-BEAM        (≈ 27 cells × 3 seeds, ~3h)
    E5             (3 seeds × LoCoMo, ~3h)   — runs after E1-LoCoMo to share Postgres warmup
    E3             (30 runs on BEAM, ~4h)    — runs after E1-BEAM

  Lane B (independent corpora, can run on a second machine if available):
    E2-1k, E2-10k, E2-100k    (~6h total)
    E2-1M                     (~12h, may halt at 12h cap)

  Lane C (long-running, low CPU during drip-feed sleep cycles):
    E4 (3 seeds × 100k drip-feed, ~36h)

Critical-path total on a single machine: ~76h (≈ 3 days) post-E6.
With Lane B parallelized: ~52h (≈ 2.2 days) post-E6.
```

**Dependencies.**
- E1, E2, E3, E4, E5 depend on E6's `caller_tag` exclusion being verified (otherwise
  scored runs would inflate write counters and contaminate C6).
- E5 depends on the LongMemEval-tuned config being frozen at protocol-freeze commit.
- E3 sweeps a `compute_decay` constant; must run AFTER E1's decay-disabled row to
  cross-check that "λ=1.0 in E3" matches "decay-disabled in E1" within seed variance.
- E4 is independent of all others.

---

## Sign-off requirements before any scored run

1. Protocol-freeze commit exists and is clean (`git status --porcelain` empty).
2. Embedding cache built; SHA-256 recorded.
3. Frozen LongMemEval-tuned config file committed; SHA-256 recorded.
4. E6 instrumentation deployed; `caller_tag` exclusion exercised in a smoke test.
5. Negative-result log file initialized.
6. This document referenced in the commit message of every scored run.

Any deviation produces an addendum file `tasks/verification-protocol-addendum-NNN.md`,
not an edit to this file.
