# Fisher experimental-design protocol — Layout Authority at scale

**Procedure.** The design *is* the experiment. Curie identified ~28 unmeasured
quantities; this protocol pre-specifies the factorial design, randomization,
blocking, replication, and analysis plan that would actually settle them.
Anything observed outside this plan ships as `// STATUS: exploratory`.

---

## 1. Hypothesis (the causal claims under test)

- **H1 (latency).** End-to-end slot-write latency p99 is determined by
  `(N, S, K)` — node count, subscriber count, kind mix — and is independent
  of insertion order under randomized arrival.
- **H2 (drops).** Dead-queue dropouts are a function of `(S, K, R)` where
  `R` = subscriber drain rate; they are zero in the `S=1, R≥emit_rate`
  regime and grow super-linearly above a threshold fill ratio.
- **H3 (memory).** RSS at saturation is linear in `S` and sub-linear in
  `N` (counters scale with kinds, not nodes); Curie C13/C18 80 B/item
  estimate is within ±20% of measured `tracemalloc` peaks.
- **H4 (throughput).** Single-core slot/s rate is invariant under kind mix
  for closed-form geometry (Curie C7 disagrees: memory=295 ms vs
  setup=180 ms suggests a 60% kind effect — re-test with replication).

---

## 2. Factors and levels

| Factor | Symbol | Levels | Role |
|---|---|---|---|
| Node count | N | {10⁴, 10⁵, 10⁶} | treatment (3) |
| Subscriber count | S | {1, 10, 100} | treatment (3) |
| Kind mix | K | symbol-heavy (70/20/10), file-heavy (20/70/10), balanced (33/33/34) | treatment (3) |
| Hardware | H | {M-series-laptop, x86-server, CI-runner} | block |
| Python build | P | {3.10-stock, 3.11-stock} | block |
| Random seed | σ | 5 levels (replicates within block) | replication |

**Total cells:** 3·3·3 = **27 treatment combinations**, full factorial.
**Replicates:** 5 seeds × 2 Python builds × 3 hardware = **30 reps/cell**
→ **810 runs total**. Power-trim (§5) reduces to ~270 if interactions
prove negligible at first 27-run pilot.

---

## 3. Response variables (pre-specified, with sufficient statistics)

| Symbol | Quantity | Instrument | Sufficient stat |
|---|---|---|---|
| L_e2e | end-to-end latency emit→subscriber recv (ns) | `perf_counter_ns()` paired timestamps | (count, sum, sum², p50, p99, max) per cell |
| D | dropped events (count) | `_log.dropped_total` counter | (sum, max-streak) per cell |
| M_peak | RSS peak (bytes) | `resource.getrusage(RUSAGE_SELF).ru_maxrss` + `tracemalloc.get_traced_memory()` | (max, mean) per cell |
| T_slot | slot/s throughput | `bench_geometry`-style ns/op | (mean, sd, n) per cell |
| Q_depth | per-priority queue depth distribution | sample every 10ms | histogram (10 buckets) per cell |

**Primary endpoint:** L_e2e p99 (H1). Everything else is secondary —
declared now to prevent post-hoc cherry-picking.

---

## 4. Design — randomized complete block factorial

- **Block on** (H, P): each (hardware, Python) combination is a block.
  Block effects are removed before testing treatment effects.
- **Within each block**, run all 27 (N,S,K) cells in a randomized order
  (Mersenne-Twister, seed = 0xF15HE2). The order is generated once,
  written to `runs.csv`, executed by the harness, never re-shuffled.
- **Within each cell**, replicate over 5 σ seeds. Seeds determine
  arrival permutation of node ids and kind assignment.
- **Warm-up:** 1 discarded run per block before measurement (JIT/page-
  cache stabilization). Discard pre-registered, not post-hoc.

**Why this structure:**
- *Randomization* (run order) eliminates time-of-day, thermal, and
  background-process confounds.
- *Blocking* (H, P) removes hardware/runtime variance from the
  treatment-effect error term — sharpens the test.
- *Replication* (σ) estimates within-cell variance so the F-test on
  treatment effects is well-defined.
- *Factorial* (N×S×K) detects interactions Curie missed: e.g. does the
  kind effect (H4) change with subscriber count? One-at-a-time would
  never see it.

---

## 5. Power calculation (pre-run, not post-hoc)

- Expected effect size for L_e2e p99 across N levels: log-linear, ~10×
  per decade. Cohen's f ≈ 1.5 (huge effect).
- Expected effect size for K main effect: ≤ 60% (Curie C7), f ≈ 0.4.
- Expected N×S interaction: unknown — pilot first.
- For the smallest effect of interest (K main effect, f=0.4) at α=0.05,
  power=0.9, 3 levels: required n=21 per level → **27 runs/block × 1
  block ≈ 90 runs covers K with margin**. The 30-rep budget is far
  above floor.
- Stopping rule: run all 27 cells × 5 seeds in pilot block (M-series
  laptop, Python 3.10) — 135 runs. If K main effect F-test p>0.1 AND
  interactions p>0.1, drop to 1 seed for the remaining blocks.

---

## 6. Confound audit

| Potential confound | Controlled by | If uncontrolled: consequence |
|---|---|---|
| Time-of-day thermal throttling | randomized run order within block | latency would correlate with cell index |
| Subscriber slow-consumer artifact | S=1 baseline + simulated 1 MB/s consumer at S>1 (pre-spec'd drain rate R) | drops blamed on emit instead of drain |
| Insertion order (clustered vs random) | σ seed permutes arrival; report both ordered and shuffled as a 2-level factor in pilot | hash-collision artifacts inflate one cell |
| Filesystem cache for `_wire` framing | flush page cache before each block on Linux; one warm-up run on macOS | first-run-of-block always faster |
| GC pauses | `gc.disable()` during measurement window; record `gc.get_count()` deltas | bimodal latency distribution |
| Network loopback variance (SSE) | localhost only; record `lo` MTU; disable Nagle on test socket | p99 inflated by transport, not authority |
| `tracemalloc` overhead | enable only in M_peak runs (separate sub-experiment); never during L_e2e cells | latency runs slowed 30% |

---

## 7. Analysis plan (pre-specified)

- **Primary test:** 3-way ANOVA on `log10(L_e2e_p99)` with factors
  (N, S, K) and blocks (H, P). Model:
  `log L = μ + α_N + β_S + γ_K + (αβ)_NS + (αγ)_NK + (βγ)_SK + (αβγ)_NSK + block + ε`.
- **Decision rule:** report effect sizes (η²) AND F-test p-values AND
  95% CIs. *No* "p<0.05 = significant" gate — Fisher's own objection
  to that practice stands.
- **Secondary:** drops vs (S, R) — Poisson regression with offset
  `log(emit_rate × duration)`.
- **Tertiary (exploratory, labeled as such):** hardware × treatment
  interactions; kind-mix asymmetry within symbol-heavy.
- **Pre-registered table of cells where Curie's claims would be
  falsified:**
  - C13 falsified if measured 80 B/item is outside [64, 96] B in any cell.
  - C7 kind-mix dependence falsified if K main effect η² < 0.05.
  - C19 (P4=64k cap) falsified if drops occur at fill ratio < 0.6 in
    (S=100, K=balanced, N=10⁶).

---

## 8. Harness deliverables (engineer hand-off)

1. `bench_layout_authority_factorial.py`
   - reads `runs.csv` (pre-randomized order)
   - emits per-run row: `(block_id, cell_id, σ, N, S, K, L_p50, L_p99,
     L_max, D, M_peak_rss, M_peak_traced, T_slot, gc_count_delta, runtime_s)`
   - writes to `bench_results/factorial_<isodate>.csv`
2. `analyze_factorial.py` — runs the §7 ANOVA, prints effect-size
   table, writes `bench_results/factorial_<isodate>_anova.json`.
3. `runs.csv` generator — `gen_runs.py --seed 0xF15HE2 --blocks H,P`
   produces the canonical run order; commit the CSV.
4. Slow-consumer simulator — `sse_slow_consumer.py --rate 1MB/s`
   used as the S>1 drain target.

Naming convention `factorial_<isodate>` is load-bearing — analysis
scripts depend on it.

---

## 9. Order of execution

1. **Pilot block** (M-series, Python 3.10): 27 cells × 5 seeds = 135 runs.
   ~2 hours wall. Settles power calculation for full grid.
2. **Memory sub-experiment** (separate run, `tracemalloc` enabled): 27
   cells × 1 seed = 27 runs. Resolves H3 / Curie C4, C13, C18.
3. **Full factorial** if pilot reveals non-trivial interactions: 30
   reps/cell × 27 cells = 810 runs across 6 (H,P) blocks.
4. **Falsification tests** (§7 pre-registered): run regardless of pilot
   outcome.

---

## 10. Refusal markers

- Any attempt to re-shuffle runs after seeing data → exploratory tag.
- Any new metric introduced after the harness runs → `secondary,
  unregistered` tag in the report; cannot be the headline claim.
- Any cell run only once and reported as evidence of an effect →
  refused; H4 (kind-mix) specifically requires the pilot's 5 reps.
- Single-machine results presented as "the" performance number → must
  carry block_id; cross-block claims require ≥2 H levels.

---

## 11. Hand-offs

- **Implementation of harness §8** → engineer.
- **`tracemalloc` peak instrumentation** → engineer (specs in
  curie.md §3 already; this protocol blocks them per (N,S,K) cell).
- **Causal-graph audit of slow-consumer pipeline** → Pearl (Curie
  flagged this; needed to interpret D vs R).
- **Hash-uniformity audit of `_stable_hash` over the σ seed range**
  → Mandelbrot.
- **Long-horizon drift observation** (does p99 walk over hours?) →
  Darwin — out of scope for this factorial; needs separate protocol.

---

## 12. One-line verdict

The Curie audit named **28 unmeasured carriers**; this protocol pre-
specifies the **27-cell factorial × 30 replicates** that resolves them
without post-hoc selection. The design is the experiment; the data
collection is clerical.
