# Curie measurement-discipline audit — Layout Authority

**Procedure:** the instrument is the arbiter. Every quantitative claim must
point to (a) apparatus, (b) unit and noise floor, (c) next experiment that
would falsify it. Estimates without a protocol are carriers-of-an-unknown.

Files audited: 6× `layout_authority_*.py`, `bench_layout_authority.py`,
`cost-model.md`.

---

## 1. Survey of every quantitative claim

| # | Claim | Source file:line | Class |
|---|---|---|---|
| C1  | "10⁹ nodes in 1–2 s" budget | cost-model.md:5 | derived ceiling |
| C2  | "1 ns / node ≈ 3 cycles" | cost-model.md:11–14 | architectural axiom |
| C3  | "~10 ns / node single-core Python at 10⁸" | cost-model.md:18 | extrapolation, no measurement |
| C4  | "8 MB working set ceiling" | cost-model.md:5,42 | self-imposed budget |
| C5  | "11 domains × 6 kinds × 8B = 528 B" counter state | cost-model.md:50 | arithmetic, exact |
| C6  | "7 tools × 11 domains × 16B ≈ 1.2 KB" angle cache | cost-model.md:53 | arithmetic, exact |
| C7  | Per-kind benchmarks: 180.1 / 211.9 / 295.7 / 201.6 / 198.6 ms per 1M ops | cost-model.md:80–85 | one measured run, single machine |
| C8  | "3.4–5.6 M slots/s per core ≈ 180–300 ns/slot" | cost-model.md:87 | derived from C7 |
| C9  | "20–30× faster needed via numpy/SSE writes" | cost-model.md:88 | unmeasured speculation |
| C10 | "numpy vectorised ~30–50 ns/slot, ~50× speedup" | cost-model.md:91 | unmeasured speculation |
| C11 | "8-core parallel write 5–8× on top" | cost-model.md:93 | unmeasured speculation |
| C12 | Event log cap = 500_000 events | _log.py:42 | hardcoded |
| C13 | "~80 B / event payload + 32 B tuple" → ~56 MB worst case | _log.py:13 | arithmetic from estimate |
| C14 | Subscriber queue cap = 100_000 | _log.py:43 | hardcoded |
| C15 | Dead-queue miss threshold = 200 consecutive failures | _log.py:44 | hardcoded |
| C16 | Pending-edges buffer = 100k (default) | _protocol.py:I5 | spec, not yet implemented |
| C17 | QUEUE_SIZES per priority: 1k / 1k / 16k / 32k / 64k / 128k / 100 | _scheduler.py:78–86 | hardcoded |
| C18 | Scheduler worst-case ≈ 19.4 MB | _scheduler.py:54–62 | arithmetic from 80 B/item estimate |
| C19 | "P4=500k × 80 B = 40 MB breaches 8 MB" → cap at 64k | _scheduler.py:50 | arithmetic, dependent on 80 B claim |
| C20 | `is_overloaded` threshold = 0.8 of cap | _scheduler.py:253 | hardcoded |
| C21 | LOD power-law `stride = 2^(3 − 4·zoom)` | _lod.py:10–18 | declared model |
| C22 | LOD log-log slope tolerance ±0.05 around −1.0 | _lod.py:190 | tolerance only, no real-data measurement |
| C23 | Far-zoom threshold = 0.4, far-reduced stride = 2 | _lod.py:52–55 | hardcoded |
| C24 | "JSON parse ~250 ns vs JSON.parse ~1 µs / 5-field object" | _wire.py:24 | unsourced micro-bench |
| C25 | "SSE framing ≈ 30 B / event irreducible" | _wire.py:16 | arithmetic from format string |
| C26 | "typical slot payload ~52 B → ~82 B / event" | _wire.py:18–20 | example, not population mean |
| C27 | Float format `:.1f` "sub-pixel invisible at FILE_R=220" | _wire.py:99–101 | qualitative, not measured |
| C28 | Coordinate radii: 70 / 140 / 220 / 150 / 150 / 50 / 290 / 32 / 18 | _geometry.py:28–36 | copied from JS upstream |
| C29 | Sector half-widths: π/2.6, π/6.5, 0.72π | _geometry.py:39–41 | copied from JS upstream |
| C30 | base_radius "42 % of min(W,H)" + spacing floor | _geometry.py:67 | copied from JS upstream |

---

## 2. Per-claim measurement protocol

### Geometry (C2, C3, C7–C11)
- Instrument of record: `bench_geometry` — `perf_counter_ns()`, ns/op.
  Noise floor ≈100 ns on macOS. C7 is the only measured claim, single
  run, single machine, no error bars.
- C3, C9, C10, C11 are speculation. Required:
  1. `bench_geometry_numpy`: vectorise over 64k-node batches per kind;
     pass criterion ≤50 ns/op median, 5 runs.
  2. `bench_geometry_parallel`: `ProcessPool` N=1..8; pass
     criterion scaling ≥0.7·N up to 8 cores.
  3. Run on ≥3 machines; report median + IQR.
- C2 (3 cycles) is a reasoning aid, not a budget — flag in cost-model.

### Memory ceiling (C4, C5, C6, C13, C18, C19)
- Instrument missing. No RSS / `tracemalloc` anywhere. C13 and C18
  are arithmetic on an estimated 80 B/item that is itself unverified.
- Required: `bench_memory_residency` using `tracemalloc.start()` +
  `get_traced_memory()` peak per component and per priority queue at
  saturation; verify 80 B/item with `sys.getsizeof(NodeDelta(...))`
  plus deque overhead. Falsifier: peak > 8 MB during integration bench.

### Event log (C12, C14, C15)
- C12 (500k cap): no protocol justifies the specific number. Required:
  per-build histogram of `(now − client_last_event_id_age)` at
  reconnect. Cap should sit at the 95th percentile of stream-events-
  during-reconnect-window.
- C14 (100k subscriber queue): not measured. Required: harness driving
  `emit()` at 100k events/s into a simulated 1 MB/s consumer; verify
  queue depth distribution.
- C15 (200 misses → dead): arbitrary. Required: measure the
  consecutive-`put_nowait`-failure distribution on a healthy-but-slow
  consumer; set threshold at 99.9th percentile, not at a round number.

### Scheduler (C17, C19, C20)
- C17 (per-priority caps): each cap should = (drain rate × tolerated
  burst latency) − steady-state population. None of those three
  quantities is measured. Required: instrument submit/pop timestamps,
  report 90th-percentile residency time per priority on a real build.
- C19 (P4=64k): chain "500k × 80 B = 40 MB > 8 MB" depends on the
  unverified 80 B. Re-derive once C13 lands.
- C20 (overload = 0.8): pick by measurement. At what fill ratio does
  drop-rate become non-zero in steady state? That value is the
  actionable threshold; 0.8 is a guess.

### LOD power law (C21, C22, C23)
- C22 is **the strongest protocol in the module**: `_selfcheck_powerlaw`
  materialises 10⁶ ids, fits log-log slope, asserts ±0.05 of −1.
  Right shape.
- Gaps: (a) test uses synthetic `sym:i` ids; real workloads use
  `<file>:<symbol>` strings — re-run on production sample. (b)
  Tolerance ±0.05 is asserted, not derived; should be a KS
  goodness-of-fit on the hash distribution.
- C23 (zoom 0.4 / stride 2): both numbers are guesses. Required:
  measure user-perceived missing-data at each canonical zoom.

### Wire (C24, C25, C26, C27)
- C24 ("250 ns split vs 1 µs JSON.parse"): unsourced. Required:
  committed node.js + browser microbench with the same sample
  payload. Until then, pipe-vs-JSON is preference, not evidence.
- C25/C26 (30 B framing + 52 B payload): arithmetic on one sample.
  Required: histogram of `len(format_slot(...))` over a 1M-slot
  workload — tail nodes may double payload size.
- C27 (`:.1f` sub-pixel): untested. Required: render at DPR ∈
  {1.0, 1.5, 2.0, 3.0}, confirm no visible jitter under pan/zoom;
  bump to `:.2f` for retina if it fails.

### Geometry constants (C28, C29, C30)
- Provenance is the strongest in the module — every constant carries
  `source: ui/unified/js/workflow_graph.js:<line>`. That is "two
  independent methods" applied to constants.
- Missing: pixel-level golden test. For a fixed RNG seed at N=1k,
  Python and JS layouts must agree.

---

## 3. Top-priority next experiments (ordered)

1. **`bench_memory_residency`** (C4, C13, C18) — `tracemalloc` peak
   bytes per component. One day's work; resolves four unmeasured
   claims at once.
2. **Numpy / multi-core geometry bench** (C3, C9, C10, C11) — without
   this, the "10⁹ in 1–2 s" budget is aspiration, not engineering.
3. **Real-id LOD self-check** (C22) — re-run `_selfcheck_powerlaw`
   on a sample of production node ids; refit slope.
4. **SSE consumer drain harness** (C14, C15) — drives a slow
   consumer; reports queue-depth distribution and miss-streak
   distribution. Sets C15 from the 99.9th percentile of healthy.
5. **Pixel-level JS/Python golden test** (C28–C30) — confirms the
   port preserves the upstream layout.
6. **Browser pipe-vs-JSON microbench** (C24) — closes the encoding
   choice with evidence, not preference.

---

## 4. Refusal markers

- C2 ("3 cycles per node") is a *reasoning aid*, not a budget. No
  measurement protocol can confirm it for a Python program; flag
  in cost-model.md.
- C9–C11 are speculation chains. They MUST be tagged
  `// HYPOTHESIS — no measurement` until experiments 2 above runs.
- C24 must not be cited as evidence in design discussions until
  the browser microbench is committed.

---

## 5. Hand-offs

- **Mechanism / "why does the SSE consumer slow down"** → Pearl
  (causal-graph audit of consumer pipeline).
- **Implementation of `bench_memory_residency` and numpy variant** →
  engineer agent. Specs in §3 above.
- **Statistical audit of the hash uniformity used by `_stable_hash`**
  → Fisher / Mandelbrot (already started in mandelbrot.md).

---

## 6. One-line verdict

The module has **one** claim with a real measurement protocol
(LOD power-law self-check); **one** claim with a real but
under-reported measurement (geometry ns/op on one machine); and
**twenty-eight** claims that are estimates, arithmetic on
estimates, or speculation. The carriers of those residuals are
named above; isolation procedures are in §3.
