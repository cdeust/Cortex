# Ibn Khaldun audit — structural plausibility of layout-authority claims

**Method.** Before evaluating who said what, test each claim against the
structural constraints of the domain (memory accounting, wire bandwidth,
Python interpreter cost, browser render rate). A claim from a careful
auditor that violates domain constraints is rejected before the
auditor's reputation is consulted. *Authority is not evidence;
structural plausibility is.*

A claim can be **locally true** (correct for one module read in isolation)
yet **structurally implausible** as a system-wide statement. Most
violations here are of that form: a number scoped correctly to a single
module is then re-quoted as a system budget.

---

## 1. Plausibility filter — top-line claims

| # | Claim | Domain constraint | Plausible as a SYSTEM claim? | Reasoning |
|---|---|---|---|---|
| K1 | "8 MB working-set ceiling" (cost-model.md:5,42) | Σ of all live allocations: scheduler + log + sub queues + numpy + interpreter | **No** | Scheduler worst-case 19.4 MB (Curie C18, Dijkstra B1); event log 500k × 80–112 B = 40–56 MB (Curie C13, Dijkstra B2); each subscriber queue 100k × ~112 B ≈ 11 MB (Fermi). Sum is **~70–90 MB**, ~10× the ceiling. The 528 B counter figure is true for geometry only; that is what the budget actually buys. |
| K2 | "10⁹ nodes in 1–2 s" (cost-model.md:5) | wall-time = max(compute, wire, render) | **No** | Fermi independently brackets full build at **10⁴–10⁵ s (3–30 h)**, ×4 with edges. 10⁹ × 80 B = 80 GB over wire; even at 1 GB/s loopback that is 80 s, and the realistic SSE channel is 10–100 MB/s → 10³–10⁴ s. Browser render at 10⁴–10⁵ evt/s → 10⁴–10⁵ s. The 1–2 s bound holds for *closed-form geometry IF vectorised*, not for end-to-end placement-and-stream. |
| K3 | "≈10 ns/slot achievable via numpy + 8-core" (cost-model.md:88–93) | Python attribute access ~100 ns; numpy batch amortised ~30–50 ns IF batched | **Speculative** | Curie C9–C11 explicitly flag as "unmeasured speculation". Plausible as a *target*, not as a budget line. |
| K4 | "no per-event recompute, O(1) per node" | closed-form geometry; counter increment + trig | **Yes** | Archimedes proves boundedness, finiteness, and per-kind interval arithmetic from source. Independence (planetary heuristic + interval bounds) holds. |
| K5 | "528 B counter state for 11×6" | 11 × 6 × 8 B int64 | **Yes** | Pure arithmetic; verifiable by inspection. But this is the geometry-module's per-domain state, not the authority's total residency. |
| K6 | "180–300 ns/slot pure Python" (cost-model.md:80–87) | `perf_counter_ns()` over 1M iters | **Yes** | Curie C7 — measured (single machine, single run, no error bars; weak as evidence but structurally consistent with Python attribute/dict cost). |
| K7 | "scheduler ≤ 19.4 MB worst-case" (`_scheduler` docstring) | Σ QUEUE_SIZES × ~80 B | **Yes (and decisive)** | Internally consistent arithmetic. *This is the structural refutation of K1*: the same module says 19 MB while the cost model says 8 MB. Two parts of the spec contradict; only one can be the system budget. |
| K8 | "200-miss dead-queue threshold, 0.8 overload" (`_log.py`, `_scheduler.py`) | should derive from drain-rate × tolerated lag | **No** | Round numbers, no measurement (Curie C15, C20). Defensible as defaults; not defensible as engineered thresholds. |
| K9 | "DISC↔MEM lanes never collide" (implicit in geometry) | angular-sector arithmetic | **Conditionally** | Archimedes Caveat: collision possible when `0.04·n_disc + 0.03·n_mem ≳ 0.79 rad`. Plausible at typical N, implausible at the 10⁹ regime the cost model claims to support. |
| K10 | "browser render at 60 fps × 10³ nodes/frame ≈ 6×10⁴ evt/s" (Fermi) | 60 Hz × per-frame batch size | **Yes (as upper bound)** | Order-of-magnitude consistent with WebGL practice; refutes K2 from the consumer side. |

---

## 2. The asabiyyah pattern — why these implausibilities survived review

**Founding vigor:** the geometry module was scoped tight (counter
state, closed-form math, copied JS constants). The numbers in that
scope are exact and defensible (K4, K5, K6).

**Scope creep at the centre:** as the spec expanded to scheduler, log,
wire, and SSE transport, the *original* budget figures (8 MB, 1–2 s)
were carried forward unchanged into a system whose constraints are no
longer the same. Counters at 528 B and event logs at 56 MB are not on
the same scale; treating them as one budget is the classic Khaldunian
move where the founding-phase rigor is invoked as authority for
claims it never covered.

**Peripheral challenger displaces:** Curie's measurement audit (28 of
30 claims unmeasured) and Fermi's independent bracketing (10⁴–10⁵ s
for full 10⁹ build) come from outside the cost-model.md frame and
displace its top-line claims by structural argument. Dijkstra B1
explicitly notes "exceeds 8 MB cost-model ceiling" — same observation
from a third independent reviewer.

When three independent audits with different methods converge on
"the system-wide budget is wrong by 1–2 orders of magnitude," the
structural verdict is settled regardless of which auditor is most
senior.

---

## 3. Four-cause check on the two contested claims

| Claim | Material (substrate) | Formal (pattern) | Efficient (mechanism) | Final (purpose) | Complete? |
|---|---|---|---|---|---|
| K1 8 MB | int64 counters in dict | per-domain × per-kind | `counter[(d,k)] += 1` | bound geometry-module state | **No** — material/formal/efficient/final all describe geometry; the system has scheduler + log + queues that share the process RSS. The "system budget" claim has no material referent. |
| K2 1–2 s | closed-form trig per slot | O(1) per node | numpy batch (speculated) | place 10⁹ nodes for live render | **No** — efficient cause covers compute only; wire and render mechanisms are absent from the derivation, yet they dominate (Fermi). Final cause ("live render of 10⁹") is incompatible with efficient cause (browser at ≤10⁵ evt/s ⇒ ≥3 h). |

---

## 4. Confirmation-bias audit

**Hypothesis under test (cost-model.md):** the geometry's O(1) per-node
property generalises into a system that places 10⁹ nodes in 1–2 s
within 8 MB.

**Disconfirming evidence searched & found:**
- Fermi independent decomposition: 10⁴–10⁵ s, not 1–2 s. ✓ disconfirms K2.
- Curie measurement audit: 28/30 claims unmeasured, including all the
  load-bearing "8 MB" and "1–2 s" extrapolations. ✓ disconfirms K1, K2.
- Dijkstra B1: "Scheduler residency ≤ 19.4 MB worst-case. Exceeds 8 MB
  cost-model ceiling." ✓ disconfirms K1 internally.
- Archimedes Caveat: DISC↔MEM angular collision at high N. ✓ disconfirms
  the implicit "10⁹ scales without geometric breakdown".

The disconfirming evidence is already in the audit corpus. It was not
synthesised into the cost model. That is the bias: each audit is
correct in its frame; the cost-model.md never updated when the frames
combined.

---

## 5. Verdict

| Claim | Plausibility | Action |
|---|---|---|
| K1 8 MB system-wide | **Reject** | Scope to "geometry module per-domain state ≤ 528 B"; system RSS budget belongs in an ADR with measured numbers (Curie experiment §3.1). |
| K2 1–2 s end-to-end at 10⁹ | **Reject** | Re-state as "closed-form geometry compute ≤ 1–2 s at 10⁹ IF vectorised, IF tile-served (no live SSE), IF render is offline". The user-visible 10⁹ build is hours, per Fermi and `tasks/tile-server-plan.md`. |
| K3 numpy 10 ns/slot target | **Hold** | Tag `// HYPOTHESIS — no measurement` per Curie §4 until `bench_geometry_numpy` lands. |
| K4 O(1) per node | **Accept** | Archimedes verified; independence holds. |
| K5 528 B geometry counters | **Accept** | Arithmetic. |
| K6 180–300 ns/slot pure Python | **Accept (single-run caveat)** | Replicate on ≥3 machines with IQR (Curie §3). |
| K7 scheduler 19.4 MB | **Accept** | And note that this *settles* K1 — system memory budget is not 8 MB. |
| K8 200-miss / 0.8 thresholds | **Hold** | Engineer to derive from measured distributions, not round numbers. |
| K9 DISC↔MEM non-collision | **Conditional** | Holds at production N; tighten arc growth before claiming 10⁹ scale. |

---

## 6. Hand-offs

- **Engineer:** rewrite cost-model.md §1 and §3 to scope "8 MB" and
  "1–2 s" to the geometry module only. Add a separate system-budget
  ADR citing Dijkstra B1 + Curie §3.1 instrumentation requirement.
- **Curie:** prioritise `bench_memory_residency` (top of her §3 list);
  one measurement collapses K1, K7, B1 into a defended number.
- **Fermi:** the binding constraint is browser render throughput;
  measure it on the tilemap path at 10⁵, 10⁶, 10⁷ to lock K2's bracket.
- **Lamport:** if the 10⁹-scale invariants are kept (DISC↔MEM
  separation, parent-before-child ordering), TLA+ them; the structural
  argument here is sufficient at production N but not at the claimed
  ceiling.

## 7. One-line verdict

The geometry module's claims are structurally sound. Their promotion
to system-wide claims is structurally implausible — by ~10× on memory
and ~10⁴× on wall time — and three independent audits already say so.
