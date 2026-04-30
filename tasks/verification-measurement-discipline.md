# Verification Measurement Discipline (Curie Addendum)

Companion to `tasks/verification-protocol.md` (drafted in parallel). Every number reported by E1-E6 must trace through this audit. No interpolation, no estimation. Where the instrument cannot produce the number, the cell stays empty with `// TODO: <reason>`.

Convention: `bench/lib` = `benchmarks/lib/`, `bench/<name>` = `benchmarks/<name>/`.

---

## Per-Experiment Audit

### E1 — Benchmark scores (LongMemEval, LoCoMo, BEAM headline)

1. **Instrument.** `bench/longmemeval/run_benchmark.py` (R@k, MRR), `bench/locomo/run_benchmark.py`, `bench/beam/run_benchmark.py`. Score emission flows through `bench/lib/reporting.py`. Latency clock: currently `time.monotonic()` (line 142, 210 of longmemeval) — REPLACE with `time.perf_counter()` for sub-ms resolution; keep monotonic for wall-clock slot.
2. **Comparand.** Best-in-paper score from each benchmark's source publication (LongMemEval ICLR 2025, LoCoMo ACL 2024, BEAM ICLR 2026). Cite paper + table.
3. **Noise floor.** Currently UNKNOWN. Required: 5 reruns on clean DB (same seed where supported, different seed where not), report mean ± stdev. Without σ, `97.8% vs 78.4%` is suggestive but not licensed.
4. **Not measured but should be.** (a) Embedding-model variance — lock `EMBEDDING_MODEL=<exact-name>:<exact-revision>`. (b) GC variance — `PYTHONMALLOC=malloc gc.disable()` around the recall loop. (c) PG plan cache — `psql -c "DISCARD ALL"` between reruns. (d) HNSW index build determinism — pgvector HNSW is not order-deterministic; record build seed if exposed, otherwise document non-determinism as an irreducible noise source.

### E2 — Ablation deltas (BEAM)

1. **Instrument.** `bench/beam/ablation.py` (322 lines). Reads ablation flags, runs benchmark, emits per-mechanism Δ.
2. **Comparand.** Full-system baseline must be **re-measured in the same process invocation** as the ablated runs — not pulled from `CLAUDE.md`. Stale baseline drift is data, not noise.
3. **Noise floor.** Per-mechanism σ from 5 reruns of the unablated config. Smallest detectable effect (SDE) = 2σ. Any ablation Δ below SDE is reported as "below noise floor" — not as 0.
4. **Not measured but should be.** Order effects: ablations run sequentially share PG state. Either (a) tear down + rebuild DB between each ablation, or (b) randomize order across the 5 reruns and report whether the Δ is order-stable.
5. **Structural gap.** No DB-snapshot/restore primitive in `bench/lib/bench_db.py`. Without it, "clean DB" means full re-ingest per run (slow). See measurement-debt.

### E3 — Decay-sensitivity sweep

1. **Instrument.** Decay curve emitted by sweeping `CORTEX_DECAY_RATE` (or equivalent env var in `mcp_server/infrastructure/memory_config.py`) across N values, re-running BEAM at each.
2. **Comparand.** Score at default decay rate (the value committed to `memory_config.py`).
3. **Noise floor.** Per-point σ from 3 reruns. The curve's slope is meaningful only where |Δscore| > 2σ. Plot σ as error bars.
4. **Not measured but should be.** Confounding with consolidation cadence — if the decay sweep also alters consolidation timing implicitly, the curve mixes two effects. Pin `CONSOLIDATION_INTERVAL` explicitly across the sweep.

### E4 — Longitudinal recall (multi-session, same corpus)

1. **Instrument.** Repeated `recall` calls across simulated sessions, with intermediate `consolidate` and `decay`. Ground-truth answer set must be deterministic given the seed.
2. **Comparand.** First-session recall on the same query set (no consolidation, no decay applied yet).
3. **Noise floor.** Run the longitudinal sequence 3× with the same seed → if scores diverge, the system has hidden non-determinism (HNSW build, async writes, clock-dependent decay). Document the divergence; do not average it away.
4. **Not measured but should be.** Wall-clock dependence: if decay is `time.time()`-based, two runs N seconds apart give different results. Use a virtual clock (`MockClock`) injected into `core/decay_cycle.py` for reproducibility.
5. **Structural gap.** No virtual clock currently exists. Decay reads system time. See measurement-debt.

### E5 — Cross-benchmark transfer

1. **Instrument.** Run config tuned on benchmark A, evaluate on benchmark B. Report ΔB(tuned-on-A) vs ΔB(tuned-on-B).
2. **Comparand.** Per-benchmark optimal config (the one in `CLAUDE.md` benchmark scores).
3. **Noise floor.** Both A-tuned and B-tuned configs must be re-measured in the same campaign. Cross-paper score citations are not comparands — same-machine, same-DB, same-process only.
4. **Not measured but should be.** Tuning leakage: if any hyperparameter was tuned on a benchmark's *test* split, transfer numbers are inflated. Audit each tuned constant for split-provenance.

### E6 — Read/write ratios (production-shape workload)

1. **Instrument.** Counter increments around `remember()` / `recall()` in `mcp_server/handlers/`. Latency: `time.perf_counter()` per call. Memory: `tracemalloc.get_traced_memory()` snapshot before/after; `resource.getrusage(RUSAGE_SELF).ru_maxrss` as cross-check.
2. **Comparand.** Production target ratio (state it explicitly; if unknown, say "I don't know" and stop).
3. **Noise floor.** p50/p99/p999 from ≥10⁴ calls after a 100-call warmup. Report distribution, not mean.
4. **Not measured but should be.** PG connection-pool warmup; pgvector HNSW first-query cost (cold cache → 10× p99 inflation); FlashRank ONNX session cold-start.

---

## Measurement Protocol Checklist (HARD STOP before publishing any number)

1. [ ] DB started clean: `DROP DATABASE` + `CREATE DATABASE` + `pg_schema.py` migration applied.
2. [ ] `psql -c "DISCARD ALL"` between every rerun.
3. [ ] Embedding model name AND revision pinned in env; logged in result file.
4. [ ] `PYTHONHASHSEED` set; recorded.
5. [ ] `PYTHONMALLOC=malloc` exported.
6. [ ] `gc.disable()` around the measurement loop; `gc.collect()` once before; re-enable after.
7. [ ] Single process, single thread for measurement (no concurrent ingest).
8. [ ] Warmup: ≥100 queries before timing begins.
9. [ ] N = 5 reruns minimum; record per-run scores, not just mean.
10. [ ] Report mean ± stdev; flag any claim where Δ < 2σ as "below noise floor."
11. [ ] Latency: `time.perf_counter()` (NOT `time.monotonic()` — current code is wrong-tool).
12. [ ] Latency: report p50, p99, p999 — never mean alone.
13. [ ] Memory: `tracemalloc` peak + `getrusage` ru_maxrss cross-check.
14. [ ] HNSW index build seed recorded if exposed; otherwise documented as irreducible.
15. [ ] PG `EXPLAIN (ANALYZE, BUFFERS)` captured for the hot recall query at least once per campaign.
16. [ ] Plan cache flushed: `DISCARD PLANS` between configs.
17. [ ] Decay/consolidation: virtual clock used (no `time.time()` reads).
18. [ ] Ablation: full-system baseline re-measured in same campaign (no `CLAUDE.md` reuse).
19. [ ] Ablation: order randomized OR DB rebuilt between each ablation.
20. [ ] Cross-benchmark: same machine, same DB, same process — no cross-paper score comparisons.
21. [ ] Inert control: a "no-op" config (e.g. random retrieval, BM25-only) run as floor-comparand.
22. [ ] Result table columns: score, σ, n_runs, seed, embedding_rev, git_sha, db_snapshot_id, wall_date.
23. [ ] Any unmeasurable cell: empty with `// TODO: <named reason>`. NO interpolation.
24. [ ] Result file committed to git BEFORE writing the prose claim.
25. [ ] Two independent methods: every headline claim corroborated by a second instrument (e.g. R@10 + MRR; latency p99 + tracing histogram; ablation Δ + leave-one-in confirmation).
26. [ ] Observer-effect audit: instrumentation overhead measured by running with profiler off vs on; report Δ.
27. [ ] CPU governor pinned (`performance` mode); thermal headroom logged.
28. [ ] Background processes audited: no Spotlight/backup/IDE indexer during runs.
29. [ ] Reproduction: a fresh checkout + a one-shot script reproduce the headline number within 1σ.
30. [ ] If a number cannot pass items 1-29, it does not ship. Say "I don't know."

---

## The "I don't know" Rule

If any cell in any result table cannot be measured for a reason you can name, the cell stays empty with `// TODO: <reason>`. Examples of acceptable empty cells:
- `// TODO: σ unknown — single run only, rerun infrastructure pending E2 baseline harness`
- `// TODO: HNSW build non-determinism not characterized; needs pgvector seed audit`
- `// TODO: cold-cache p99 not separable from warm-cache without DISCARD ALL between calls`

Forbidden: filling a cell with an estimate, an interpolation, or a "should be roughly X."

---

## Measurement-Debt List (ordered by impact-if-wrong)

1. **LongMemEval R@10 = 97.8% / MRR = 0.882 (CLAUDE.md April 2026).** Provenance unknown — single run? Aggregated? 95% CI? **Status: I don't know.** Required: rerun ×5 on locked embedding model + commit `bench/results/longmemeval_<sha>_<date>.json` with per-run scores.
2. **BEAM Overall = 0.543.** Same questions. Higher impact-if-wrong because the headline beats best-in-paper (0.329) by a large margin — a single-run inflation here is the most damaging citation in the campaign.
3. **LoCoMo R@10 = 92.6% / MRR = 0.794.** Same questions. Same fix.
4. **All ablation Δs in `bench/beam/ablation_results.json`.** No σ. Cannot distinguish 1pp signal from 1pp noise.
5. **All latency claims (`<50ms`, `<100ms`, `<200ms` in CLAUDE.md tool table).** Targets, not measurements. No published p99. Required: emit p50/p99/p999 from a real workload trace.
6. **Cross-benchmark transfer claims.** Currently zero published numbers; any future claim must follow E5 protocol from day one.

---

## Structurally Impossible Measurements (engineer-agent action items)

These cannot be measured today without code changes. Flag for engineer agents:

1. **Ablation noise floor without DB-snapshot/restore.** `bench/lib/bench_db.py` has no snapshot primitive. Workaround = full re-ingest per run = O(minutes-hours) per ablation × 5 reruns × N mechanisms = infeasible. **Need:** `pg_dump`/`pg_restore` wrapper or filesystem-level PGDATA snapshot in `bench/lib/bench_db.py`.
2. **Deterministic longitudinal recall.** `core/decay_cycle.py` and consolidation read system time directly. **Need:** `Clock` protocol injected into core, `MockClock` for benchmarks. (DIP — core declares the port; bench provides the adapter.)
3. **HNSW build determinism.** pgvector HNSW build order is not user-seedable in current pgvector versions. **Need:** either pin pgvector version + document non-determinism as σ-floor, or rebuild via a deterministic alternative index.
4. **Embedding-model revision pinning.** `infrastructure/embedding_engine.py` loads sentence-transformers by name; revision (commit hash on HF) is not pinned. **Need:** record `model.config._commit_hash` (or equivalent) into every result file.
5. **Instrumentation overhead Δ.** No "profiler-off vs profiler-on" mode in benchmarks. **Need:** a `--no-instrument` flag that disables all `time.perf_counter` and `tracemalloc` calls for a clean reference run.
6. **`time.perf_counter` migration.** `bench/longmemeval/run_benchmark.py:142,210,218` use `time.monotonic()`. Replace.

End of audit. No claims, no interpolations.
