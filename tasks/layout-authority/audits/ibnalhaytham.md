# Ibn al-Haytham Audit — Layout Authority

> **Method:** *Al-Shukuk* applied to the Layout Authority design. Doubt is
> not general skepticism; each doubt is specific, documented, and assigned a
> resolution experiment. Authority — including prior audits in this folder —
> is not evidence. The instrument and the experiment are evidence.

## 1. Predecessor theory under doubt

The "received authority" being audited:
- `cost-model.md` (Boyd-style derivation of the 10⁹/1–2 s budget).
- The five `layout_authority_*.py` modules and their docstring claims.
- Prior audits (`curie.md`, `ramanujan.md`, `dijkstra.md`) — these are also
  authority and must be doubted in the same register, not deferred to.

## 2. Doubt document — claim by claim

| # | Authoritative claim | Source | Specific doubt | Resolution experiment | State |
|---|---|---|---|---|---|
| A1 | "8 MB working set" is the cost-floor ceiling | cost-model §1, §3 | The 8 MB number is **declared**, never derived from a target machine, page-cache budget, or measured RSS. Curie C4 confirms: no `tracemalloc`, no RSS sample, no provenance. It is a self-imposed slogan. | `bench_memory_residency`: `tracemalloc.start()` + 60 s sustained 10⁶ ev/s; report peak RSS and per-component breakdown. Falsifier: peak > 8 MB. If it falsifies, either revise the budget with a sourced rationale or shrink the queues. | **OPEN** |
| A2 | "Closed-form O(1) geometry per node" | cost-model §1 ¶3, §6 | Holds in the linear regime only. Ramanujan §"qualitative break" shows: file-arc saturates at n=18, memory-arc has a *two-term* bonus, base_radius spacing-floor only activates at N≥6 on a 1080p canvas. **The closed form has three regimes; "O(1)" hides the regime switch.** Hand-tests at N∈{1,2,3} did not exercise large-N branches at all. | `bench_geometry_branches`: sample N ∈ {1, 3, 6, 17, 18, 19, 50, 200, 11_000} per kind, assert closed-form output is finite, non-NaN, and that the *active branch* matches the regime predicted by the formula. Falsifier: any (kind, N) where output is NaN, ∞, or where two distinct nodes collide within 1 px. | **OPEN** |
| A3 | "Single-producer" rule on `_log.emit` | _log.py docstring; Dijkstra D1, H1, H2 | Documented, not enforced. Dijkstra explicitly flagged: "single-producer rule is implicit … prose only." A second thread calling `emit` silently breaks H1 (seq monotonicity) and H2 (per-subscriber order). This is a structural defect masquerading as a design rule. | `chaos_test_two_emitters`: spawn a second thread that calls `emit` 10× during a normal run; **assert** that a thread-id check at `emit` entry fires and aborts. Falsifier: the second thread succeeds, OR no assertion exists to fire. | **OPEN — until thread-id assertion lands** |
| A4 | "10 ns/node single-core Python at 10⁸" | cost-model §2, line 18 | Curie C3 marks this as extrapolation, no measurement. Measured pure-Python is 180–300 ns/slot — **18–30× the claim**. The 10 ns figure is asserted as a target *and* used as if achievable. | Run the bench at N=10⁸ on the exact target machine, single core, no JIT. Report ns/op median + IQR over 5 runs. Falsifier: median > 50 ns/op without a numpy/parallel path committed. | **OPEN** |
| A5 | "11 domains × 6 kinds × 8 B = 528 B counter state" | cost-model §3 | The arithmetic is exact, but the **assumption that domain count stays ≤ 11** is undefended. Production may grow to 50–100 domains; the 8 MB claim then needs re-derivation. Dijkstra B5 already noted this. | `bench_domain_growth`: synthesise N_domains ∈ {10, 100, 1000} and report counter + anchor-cache RSS. Falsifier: > 1 MB at N_domains=1000, or no documented hard cap. | **OPEN** |
| A6 | "Scheduler worst-case ≈ 19.4 MB" | _scheduler.py:54–62 | Dijkstra B1 and Curie C18 both flagged: the figure is arithmetic on an estimated 80 B/item that is itself unverified, AND it **already exceeds the 8 MB budget**. The design contradicts its own ceiling and nobody has reconciled it. | (a) Verify 80 B with `sys.getsizeof(NodeDelta(...))` plus deque overhead; (b) decide whether 8 MB is steady-state or peak — write the ADR. Falsifier: verified residency > 8 MB AND no ADR exists ⇒ design must change. | **OPEN** |
| A7 | "LOD power-law slope = −1 ± 0.05" | _lod.py:190 | The strongest existing protocol — but Curie C22 noted it uses synthetic `sym:i` ids, not production `<file>:<symbol>` strings. The hash distribution on real ids may have heavy tails the synthetic test misses. | Re-run `_selfcheck_powerlaw` on a 10⁶-sample of production node ids exported from the live DB. Falsifier: fitted slope outside [−1.05, −0.95] OR KS goodness-of-fit p < 0.01. | **OPEN** |
| A8 | "Field-name `slot.id` vs protocol `node_id`" (D0) | Dijkstra §0 | A type-mismatch defect was identified in a *prior* audit but I cannot assume it has been fixed. Authority (a fix in flight) is not evidence (a green test). | `pytest -k test_format_slot_protocol_match` that constructs a `SlotAssignment` and round-trips through `format_slot`. Falsifier: AttributeError or wrong field used. | **OPEN until test exists** |
| A9 | "JSON parse ~250 ns vs JSON.parse ~1 µs" | _wire.py:24 | Unsourced. Curie C24 already refused this as evidence. I echo: until a committed browser microbench exists, the claim cannot be cited in design discussions. | Commit a `bench/wire_decode_browser.html` running both decoders on 10⁵ representative payloads; report median µs/op in Chrome + Safari. Falsifier: pipe < 4× JSON.parse on either browser. | **OPEN** |
| A10 | "Pixel-equivalence with `workflow_graph.js`" | _geometry.py provenance comments | Constants are copied with `// source:` citations — provenance is good. But **the composition** of those constants under `compute_slot` has never been pixel-compared to the JS upstream. Two functions can share constants and still drift. | Golden-image test: fixed RNG seed, N=1000 mixed nodes; render JS and Python outputs to PNG; pixel-diff < 1 px median, < 3 px max. Falsifier: any node off by > 3 px. | **OPEN** |
| A11 | "Symbol n-gon non-collision (CONJ-2)" | ramanujan.md §"Conjectured closed form" | Ramanujan flagged this as a *conjecture* requiring a prover. The `(i%4)·3 px` wobble could in principle collapse two symbols. Authority labels this "medium confidence." Doubt: nobody has enumerated. | Exhaustive enumeration: for n ∈ [1, 10_000], compute all n positions and assert pairwise distance > 0. Falsifier: any (n, i, j) with i≠j producing identical (x, y). | **OPEN** |
| A12 | "Reproducibility of the 1M-slot benchmark" | cost-model §5 | The numbers (180.1 / 211.9 / …) are reported but the bench harness's environment (CPU model, thermal state, run-to-run variance, warm-up) is not in the file. One number on one machine is an anecdote per Ibn al-Haytham's *Manazir* §reproducibility. | Promote `bench_layout_authority.py` to record: machine ID, CPU model, governor, ambient temp proxy (load avg pre-run), 5 runs, IQR. Re-publish table with confidence intervals. Falsifier: IQR > 30% of median (run is too noisy to cite). | **OPEN** |

## 3. Falsification conditions, consolidated

For each authoritative claim, the **single observation that would replace
doubt with refutation**:

- A1 falsified by: `tracemalloc` peak > 8 MB at sustained 10⁶ ev/s.
- A2 falsified by: any (kind, N) producing NaN/∞ or a 1-px collision.
- A3 falsified by: a second `emit`-caller thread completing without an
  assertion firing.
- A4 falsified by: median > 50 ns/op on the target machine without numpy.
- A6 falsified by: verified scheduler residency > 8 MB AND no ADR.
- A7 falsified by: production-id slope outside [−1.05, −0.95].
- A10 falsified by: any node off > 3 px from JS upstream.
- A11 falsified by: any pair of symbols sharing (x, y).

Each falsifier names a **specific observation, a specific threshold, and
a specific instrument**. None reduces to "looks wrong."

## 4. Cross-audit doubt — the audits themselves

I do not exempt prior audits from doubt:

- **Curie's measurement table is a survey, not a measurement.** It
  enumerates 30 unmeasured claims; that enumeration is itself unverified
  until each row's experiment runs.
- **Ramanujan's hand-computation match is necessary, not sufficient.**
  Three special cases at N=1,2,3 leave the entire large-N regime
  unprobed. The audit says so; do not let "Ramanujan verified" become
  shorthand for "verified."
- **Dijkstra's correctness obligations are arguments-to-be-made, not
  arguments-made.** D0 (field-name), D1 (single-producer), D2
  (module-global) are flagged but not closed. Treat them as open until
  the engineer's `derivation.md` discharges them in writing.

## 5. The procedural mandate

No claim above is closed by another claim. Each closes only when its
named experiment runs, on the named instrument, with a recorded result
and a stated pass/fail against the falsifier. Until then the claim is
hypothesis. The cost-model is presently a **table of hypotheses
displayed as conclusions** — that is the specific failure to repair.

## 6. Hand-offs

- A1, A4, A5, A6, A12 (measurement and budget reconciliation) → **Curie
  + engineer**: implement `bench_memory_residency`, target-machine
  ns/op, IQR-reported runs.
- A2, A11 (geometry regime + n-gon enumeration) → **engineer**: write
  exhaustive `bench_geometry_branches` and the n-gon collision sweep.
- A3, A8 (single-producer enforcement, field-name fix) → **engineer**:
  thread-id assertion at `emit` entry; round-trip test through
  `format_slot`.
- A7 (LOD on real ids) → **engineer + Mandelbrot**: production-id
  sample + KS test.
- A9 (browser decode microbench) → **engineer**: committed
  `bench/wire_decode_browser.html`.
- A10 (pixel-equivalence golden) → **engineer**: JS/Python golden image
  + pixel-diff harness.

## 7. One-line verdict

Twelve specific doubts; each carries an instrument, a threshold, and a
falsifier. The Layout Authority is not refuted — it is **not yet
tested**. Until the experiments above run, the design is a coherent
proposal, not a verified instrument.
