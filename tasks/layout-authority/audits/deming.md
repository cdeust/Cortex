# Deming PDCA Audit — Layout Authority Self-Learning Capacity

**Frame:** Boyd's audit found OODA's *Act-channel* missing — no signal back to the producer. Deming asks the orthogonal question: even within the authority's own walls, does each module **close** its own PDSA cycle? A measurement that nobody studies and nobody acts on is *waste*. A correction that doesn't feed the next plan is *tampering*. The Hamilton priority discipline produces output; the question is whether the output is *learned from*.

**Verdict:** the authority is a **rich emitter, an empty learner**. CHECK exists at every module (counters, stats endpoints, SSE log size). ACT exists almost nowhere. No module's measurement updates that module's own plan. Every loop is open. The system does not learn from its own data; it merely publishes it.

Per Deming's central distinction: most "anomalies" the authority would surface are **common-cause variation** (produced by fixed caps, fixed strides, fixed thresholds). Reacting to individual events would be *tampering*. The fix is **system redesign** — change the caps/strides/thresholds based on observed distribution. That redesign capacity does not exist in code today.

---

## 1 — Per-module PDCA dissection

| Module | PLAN (implicit) | DO | CHECK (metric observed) | ACT (corrective action) | Loop closed? |
|---|---|---|---|---|---|
| `layout_authority_geometry` | "closed-form O(1) placement matches ui/unified/js conventions" | emit (x,y) per node | **NONE** — no collision metric, no overlap rate, no shell-saturation count | NONE | **OPEN** — the geometry has no observation of whether it actually fits the population it received |
| `layout_authority_lod` | "stride(zoom)=2^(3−4·zoom) yields ≈power-law visible count" | hash-decimate symbols | **NONE in module** — relies on a downstream Mandelbrot audit script for slope check | NONE — stride formula is hardcoded | **OPEN** — actual N×|visible| measurements never fed back to retune stride exponent |
| `layout_authority_scheduler` | "P0…P6 caps absorb expected burst" | non-blocking submit; priority pop | `Stats.queued`, `Stats.dropped`, `lengths`, `is_overloaded(0.8)` | **NONE** — `is_overloaded` has no production caller (Boyd §1) | **OPEN** — drops are counted but no policy adjusts caps, threshold, or producer rate |
| `layout_authority_log` | "500k ring buffer + 100k subscriber queue absorbs typical slowness" | append-only emit + fan-out | `_event_log_drops`, `_cortex_misses` per queue, dead-eviction (no counter) | reap dead subscriber after 200 misses | **HALF-CLOSED for subscribers only** — `_event_log_drops` is read by `stats()` but no caller adjusts `_EVENT_LOG_CAP`, `_DEAD_QUEUE_MISS_THRESHOLD`, or notifies clients of the drop |
| `layout_authority_protocol` | "contracts validated at boundary" | dataclass freeze | NONE — no violation counter | NONE | **OPEN** — contract violations are raised but never aggregated; the system cannot tell if a producer is chronically misshaping deltas |
| `layout_authority_wire` | "pipe-separated SSE minimizes bytes/event" | encode bytes | NONE — no per-event size histogram, no encode-time histogram | NONE | **OPEN** — Shannon claim ("~82B/event") is asserted in docstring; never measured against reality |

**Pattern:** five of six modules emit metrics or could emit metrics. Exactly **zero** consume their own metrics to alter their own behavior. The only feedback edge in the entire authority is the dead-subscriber reaper — and that is a special-cause response (specific event: client died), not a system-redesign response (the whole subscriber-cap policy never changes regardless of distribution).

---

## 2 — Common vs special cause classification

Deming's first move: classify variation before acting on it. Apply to the metrics that *do* exist:

| Metric | Likely cause class | Evidence | Correct response |
|---|---|---|---|
| `Stats.dropped[P4]` ticking under steady symbol traffic | **common-cause** — cap of 64k is part of the system | drops occur because P4 cap is fixed; producer rate is by-design > drain rate during burst | **Redesign**: raise cap, raise drain priority, OR lower producer batch size — system change, NOT per-event triage |
| `Stats.dropped[P4]` ticking once per build | **special-cause** — specific event (cold start, large repo) | one-shot at build start | Investigate that build's input size; not the system |
| `_event_log_drops` ticking | **common-cause** — 500k cap vs build size | structural; will tick on any repo > 500k events | **Redesign**: raise cap OR add a "spillover to disk" tier OR reset seq per-build (currently rejected by I3) |
| Subscriber dead-eviction | mixed | one client tab being slow = special; many = common (we are overloading the SSE format) | currently treated as special only |
| `is_overloaded(0.8)` flips True | common-cause threshold (the 0.8 is arbitrary) | unread anyway | first **read it**, then classify each transition |

The current code treats every drop as "fine, just count it." That is neither tampering nor learning — it is **agnosis**. Deming's term: *management without information*. The information is collected; the management never receives it; the system never improves.

---

## 3 — The four PDCA-closure failures

### 3.1 PLAN without prediction
The geometry, LOD, and scheduler all encode plans (formulas, strides, caps). **None of them states a prediction the system could later check**: e.g. "at 10⁸ symbols, P4 will exceed 50% capacity 0% of the time," or "stride=4 should keep visible-symbol count within ±5% of N/4." Because no prediction is recorded, no later run can be compared against it. PLAN exists, but as a frozen artifact, not a hypothesis.

### 3.2 CHECK without aggregation
`/api/layout/stats` is a *snapshot* endpoint. It reports current counters. It does NOT compute:
- rolling-window drop rates (drops/sec over last 60s)
- distributional summaries (p50/p99 queue length over the build)
- transition events (overloaded ↔ recovered, with timestamps)
- ratios (drops as % of submits per priority)

A poll-only counter endpoint is what Boyd called "yesterday's state." Deming would add: it is also "no state at all" because monotonic counters without a baseline are not yet a measurement.

### 3.3 ACT without authority
Even if a human reads `stats()` and sees P4 chronically dropping, **no module accepts a change**. Caps are module-level constants (`QUEUE_SIZES`). Stride exponent is in a docstring formula. The dead-queue threshold is `_DEAD_QUEUE_MISS_THRESHOLD = 200`. There is no `set_cap()`, no `set_stride_curve()`, no config-reload path, no admin endpoint. The Act phase requires a code change, a build, a redeploy. PDSA at deploy-time tempo cannot keep up with build-time variation.

### 3.4 No comparison against prediction
PDSA's discriminating element is **Study compares to Plan's prediction**. The closest thing today is the Mandelbrot audit script that checks the LOD slope — but that is offline, run by a human, and feeds nothing back into the running module. The slope could drift to −0.7 across releases and no one would notice unless they re-ran the audit.

---

## 4 — Sub-optimization risk (system appreciation)

Deming Move 3: never optimize a component without understanding the system. The Hamilton scheduler optimizes for *producer never blocks*. That is correct in isolation. As a system property:

- Producer never blocks → producer keeps emitting → P4 saturates → drops cascade → log fills → subscribers miss → clients render incomplete graphs.
- The local optimum (Hamilton invariant preserved) **degrades the system goal** (every node visible at appropriate zoom).
- The geometry module's O(1)-per-node optimum prevents per-node feedback by construction; you cannot decimate adaptively if the placement function refuses to look at population statistics.

This is not a bug in either module. It is the predictable consequence of optimizing each in isolation. Deming's antidote: **a module above them whose job is the system aim** (here: "every legitimately-needed node reaches every connected client"). That module does not exist.

---

## 5 — Fear / signal-suppression check

Deming Point 8 maps awkwardly to code, but operationally: are signals being suppressed somewhere they should be visible?

| Signal | Suppressed where? |
|---|---|
| `_event_log_drops` | exposed via `stats()` only — no SSE event, no log line, no alert |
| Subscriber eviction | silent — no counter, no event, no log |
| Contract violations in `add_node` / `add_edge` | raised exception then **lost** — no aggregator |
| `is_overloaded` transitions | unsurfaced; the function is uncalled |
| Per-build geometry overlap rate | never measured |

These are all data the system needs to self-correct, and all of them are dropped on the floor. Not from fear — from **inattention**. Deming would say the effect on the loop is identical: the source of corruption is upstream of the data, and no improvement method downstream can recover what was never recorded.

---

## 6 — Recommendations: instrumentation that closes the loops

Listed in **PDSA-cycle leverage order**, not module order. Each item names which module and which loop it closes.

### R1 — Add prediction artifacts (PLAN gets teeth) — *all modules*
For each tunable constant, write next to it the prediction it embodies:
```python
# QUEUE_SIZES[4] = 64_000
# prediction: P4 drop rate < 0.1% on repos with ≤ 5e6 symbols.
# check: scheduler_stats.drops[4] / scheduler_stats.queued[4] over a build.
```
Cheap. Forces the implicit hypothesis to surface so future Studies can compare.

### R2 — Rolling-window aggregator on `stats()` — *scheduler + log*
Add a `RateWindow` (60s, 600s, build-lifetime) computing drops/sec, submit/sec, queue-depth p50/p99 per priority. Without this, every metric is a counter, not a measurement. ≤80 LoC, pure logic.

### R3 — Edge-triggered PDSA events on the SSE log — *scheduler + log*
Emit `event: pdsa` with payload `{phase, prediction, actual, gap}` when `is_overloaded` transitions, when `_event_log_drops` ticks, when subscriber-eviction fires. Couples directly to Boyd's `degraded` recommendation but adds the *prediction-vs-actual* field that turns observation into Study.

### R4 — Make caps/strides/thresholds runtime-mutable via a single `LayoutPolicy` object — *all modules*
Pass `LayoutPolicy` into scheduler, log, and lod constructors. Expose a `policy.update(...)` method validated against the prediction record. This is the **ACT channel that doesn't exist today**. Without it, every learning is deploy-cycle slow. ≤120 LoC; the modules already keep their state private — surface a controlled mutator.

### R5 — Common-cause classifier — *scheduler*
A 20-line function `classify_drops(stats_window) -> CauseLabel` that distinguishes:
- chronic uniform pressure (common-cause → adjust cap),
- one-shot burst at build start (special-cause → ignore),
- single-priority anomaly (cause-specific → narrow fix).
Routes each cause to the matching ACT (R4 mutator) or to "log and wait" if special-cause.

### R6 — Geometry observation hook — *geometry*
Add an optional callback `on_place(node_delta, x, y, shell_count)`. The default is no-op. A monitor module can subscribe and aggregate (overlap rate, shell saturation) without violating O(1)-per-node — the work is offloaded to the subscriber. Closes the geometry loop without sacrificing its memory or compute claim.

### R7 — Contract violation counter — *protocol*
The dataclasses raise on bad input; the call sites catch-or-not by chance. Add a module-level `_violations: dict[str, int]` incremented in a `__post_init__` validator. Surface in `stats()`. Turns "the producer is malformed" from an invisible exception spray into a measurable rate.

### R8 — Per-build PDSA report — *new module `layout_authority_pdsa.py`*
At build end (the `done` event), emit a report:
```
{
  "predictions": [...],         # from R1 annotations
  "actuals": {...},             # from R2 windows
  "gaps": [...],                # |predicted - actual|
  "classifications": [...],     # from R5
  "recommended_policy_delta": {...},
}
```
The build-cache stores this alongside the slot/edge events. *This is the Study artifact* — the only place where PLAN is compared with DO and the gap is recorded. Without R8 the system cannot learn across builds; with it, R4's policy mutations become evidence-backed.

---

## 7 — Priority ordering (where one improvement unlocks others)

1. **R1 (prediction artifacts)** — prerequisite for R8; does not require code change to runtime modules.
2. **R2 (rolling windows)** — turns counters into measurements; prerequisite for R5, R8.
3. **R4 (LayoutPolicy + mutator)** — the missing ACT channel. Without it, R5/R8 produce recommendations that can only be applied by redeploy.
4. **R3 (PDSA SSE events)** — closes the loop to clients (complements Boyd `degraded`).
5. **R5 (cause classifier)** — gates whether ACT should fire.
6. **R6 (geometry hook), R7 (contract counter), R8 (build report)** — finish coverage of the modules currently silent.

R1+R2+R4 together make the authority *capable of learning at build tempo*. The other items are completeness; these three are sufficiency.

---

## 8 — Hand-offs

- **Boyd** — R3 (`degraded` SSE event) is the same edge as Boyd's `Act-channel` recommendation; merge implementations.
- **Hamilton** — R4 (`LayoutPolicy.update`) must preserve the never-block invariant; no mutator path can synchronously block `submit`.
- **Shannon** — R2's rolling-window rates need a budget: what drop rate per priority counts as a *signal* vs *noise*? The 0.8 threshold in `is_overloaded` is currently arbitrary.
- **Fisher** — R5's classifier needs a power analysis: how many samples in a window before "chronic vs one-shot" is statistically distinguishable?
- **Lamport** — R3's PDSA events must respect the same happens-before as `slot`/`edge` events so a client's Study reconstructs a consistent run.
