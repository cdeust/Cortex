# Taleb Audit — Fragility Classification of the Layout Authority

Stressors:
- **(a) Burst:** 10× nominal arrival for 100 ms (arrival rate spike).
- **(b) Silent disconnect:** SSE subscriber socket dies without FIN/RST.
- **(c) Malformed input:** NaN coords, missing `parent_id`, unknown `kind`.

Classification: **Fragile** (concave loss — small stress, disproportionate
damage), **Robust** (linear), **Antifragile** (convex gain — system
*improves* from the stress, e.g. the stress feeds a counter that drives
adaptive tuning).

## 1. Module-by-module triage

| Module | Stressor (a) burst | Stressor (b) disconnect | Stressor (c) malformed |
|---|---|---|---|
| `_protocol.py` | ROBUST — pure dataclasses, no runtime path | ROBUST | **FRAGILE** — `NodeDelta`/`SlotAssignment` are dataclasses; no `__post_init__` validation; NaN coords or missing `parent_id` flow downstream |
| `_geometry.py` | ROBUST — closed-form O(1) per node, no allocation | ROBUST | **FRAGILE** — `compute_slot` propagates NaN through trig (NaN×anything=NaN), poisons SSE event log |
| `_scheduler.py` | ROBUST→ANTIFRAGILE — bounded queues, drop+counter on overflow (the counter is the antifragile seed) | ROBUST | **FRAGILE** — `kind` not validated at submit; unknown kind reaches priority lookup, defaults silently |
| `_log.py` | **FRAGILE** — module-global `_event_log`, `seq`, two locks; under burst, `_fan_out` holds `_subscribers_lock` while iterating N subs × Q.put_nowait; one slow sub stalls all | **FRAGILE** — dead subscriber's queue fills to cap, every emit pays a Full-exception cost; only reaped after 200-miss window | ROBUST — emit doesn't inspect payload |
| `_wire.py` | ROBUST — pre-encoded constants, O(1) format | ROBUST | **FRAGILE** — `format_slot` reads `slot.id` (Dijkstra D0) — schema drift produces silent `None`/`AttributeError` at every emit |
| `_lod.py` | ROBUST — pure level-of-detail math | ROBUST | ROBUST iff coords pre-validated |
| `layout_authority.py` (composition root) | **FRAGILE** — single worker thread; if worker is paused (GC, page fault), P5/P6 backlog grows linearly with burst; producer is non-blocking but invisible debt accumulates | **FRAGILE** — no health probe; SSE writer thread can deadlock against a dead socket without surfacing | **FRAGILE** — `add_node`/`add_edge` validate `kind ∈ NODE_KINDS` only at protocol boundary, not at HTTP boundary; downstream raises far from the source |

## 2. Tail check — is the arrival distribution fat-tailed?

Yes. Producer is `seed_project` + LSP discovery + user-driven edits.
Empirically: discovery bursts (file walk) deliver 10⁴–10⁵ deltas in
~100 ms, then minutes of silence. Variance >> mean. **Gaussian
queue-sizing (mean × safety factor) will under-provision the burst by
1–2 orders of magnitude.** Cost-model §6 bench at 5 M slots/s assumes
steady-state; under burst the producer outruns the worker by 50–100×
for 100 ms, and queue residency spikes to the cap.

This is the Taleb-essential point: **size queues for the tail, not the
mean.** P5 (edges) at 100k cap = 10.2 MB *is the right call* if it
absorbs the discovery burst; cutting it to fit 8 MB steady-state
sacrifices burst survival to satisfy a steady-state model.

## 3. Via negativa — fragilities to remove first (priority order)

| # | Fragility | Removal | Cost |
|---|---|---|---|
| P0 | `_log` module-global state (Dijkstra D2) — two authorities corrupt each other's seq | Refactor to instance state; delete the module-level `_event_log`, `_seq`, locks | low — mechanical |
| P0 | Unvalidated `kind` at HTTP boundary — bad input reaches `_scheduler` priority map | Reject at handler with 400 + counter increment; do not let it touch the worker | low |
| P0 | NaN/Inf coords from `_geometry` propagate to wire | Add `assert math.isfinite(x) and math.isfinite(y)` at end of `compute_slot`; on fail, drop+counter, do not emit | low |
| P1 | `format_slot` field-name mismatch (`slot.id` vs `node_id`) — Dijkstra D0 | Fix `_wire`; add a contract test that exercises every protocol field | trivial |
| P1 | Dead-subscriber detection only via 200-miss window | Add a heartbeat event every 1 s; subscribers that miss 3 heartbeats are reaped immediately | low |
| P2 | `_fan_out` iterates subs while holding lock | Snapshot subs under lock, release, then `put_nowait` on the snapshot copy | low |

## 4. Barbell allocation for the layout authority

- **Safe end (≥85%):** `_geometry`, `_protocol`, `_wire`, `_lod` — pure
  functions, no I/O, no globals. Make them *boringly correct*: full
  property tests, finite-float postconditions, no clever tricks.
  Guarantee: under any input these modules either return a finite
  result or raise a typed error. **No middle ground.**
- **Experimental end (≤15%):** the scheduler's drop policy and the
  fan-out reaping policy — these are the loci where antifragility can
  be designed in (see §5). Allow these to be tuned aggressively from
  observed counters; they have bounded downside (queue cap, sub cap)
  and uncapped upside (auto-tuned to actual production stress).
- **Mediocre middle to eliminate:** "moderate" validation — partial
  field checks scattered across handler, protocol, and geometry. Pick
  ONE boundary (the HTTP handler) and validate fully there; downstream
  layers assume validated input.

## 5. Antifragility opportunities — make the stress *improve* the system

The scheduler's drop-counter is already the seed. Wire it into a
feedback loop:

1. **Burst (a) → adaptive cap.** Every `_scheduler` overflow increments
   `drops[priority]`. Expose this in `memory_stats`. When P5 drops
   exceed a threshold over a 60-s window, *raise* P5 cap by 25% (with
   a hard ceiling). When sustained zero drops over 10 min, *lower* by
   10%. Burst now *teaches* the cap. Convex: bigger bursts → faster
   discovery of the right cap. **Bounded downside:** hard ceiling
   prevents unbounded RAM growth.
2. **Disconnect (b) → faster reap.** Each silent-disconnect detection
   (heartbeat miss) decrements the reap window by 10 ms (floor 50 ms).
   The more dead subscribers we see, the faster we evict them.
   Convex: pathological deployments self-tune to aggressive reaping.
3. **Malformed (c) → schema lock-in.** Each rejected payload is logged
   with its (kind, missing_field) tuple. After N rejections of the
   same shape, surface a `tasks/layout-authority/producer-drift.md`
   alert: "the producer is sending shape X that the protocol does not
   accept — either fix the producer or extend the protocol." Malformed
   input becomes documentation of producer drift, not silent loss.
4. **Worker stall → publish a stall histogram.** If the worker loop
   spends >5 ms between pops, emit a `worker_stall` event. Operators
   tune GIL/GC settings *because* stalls were observed, not in
   anticipation of them.

In all four: the counter is visible, the policy is bounded, the stress
makes the system smarter. This is the Taleb pattern — the option, not
the obligation, to react to disorder.

## 6. Optionality audit

| Decision | Downside | Bounded? | Upside | Capped? | Verdict |
|---|---|---|---|---|---|
| Drop on P5 overflow | Lost edge event | Yes (counter) | Producer survives burst | No (any rate) | **Favorable — keep** |
| Hold global `_event_log` of 500k events | 40 MB RAM, replay cost | Yes (cap) | Late subscribers can replay | Yes (last 500k) | Favorable IF replay used; otherwise dead weight — **measure usage** |
| Single worker thread | Worker stall halts emission | **No** — unbounded latency tail | Strict ordering (H1/H2) | Yes | **Unfavorable asymmetry** — add a watchdog: if no pop in 100 ms, emit `worker_stall` and (P3) restart worker |
| `q.put_nowait` everywhere | Slow sub loses events | Yes | Producer never blocks | No | **Favorable** |

## 7. Skin-in-the-game audit

- **Producer (`seed_project`, LSP, MCP handlers):** does not bear the
  cost of malformed deltas — the layout worker eats them. **Asymmetric.**
  Fix: producer's HTTP response carries a `rejected: N` field; the
  producer sees its own malformed-rate counter and is forced to react.
- **Renderer:** does not bear the cost of slow consumption — `put_nowait`
  drops on its behalf. **Asymmetric.** Fix: SSE channel sends the
  subscriber its own miss-count; a renderer that sees its miss-count
  rising must react (paginate, downsample, or disconnect cleanly).
- **Scheduler operator:** the only actor with skin in the game today —
  RAM and CPU are paid by the process running the authority. Counters
  must surface to whoever can act: the operator, not the renderer.

## 8. Stress test plan

| Scenario | Magnitude | Expected | Acceptable? |
|---|---|---|---|
| Burst | 10⁵ deltas in 100 ms | P5 fills, drops counter ↑, slot emit continues, RSS ≤25 MB | Y once §3 P0+P1 fixed |
| Burst | 10⁶ deltas in 100 ms | drops dominate, no crash, no NaN, no deadlock | Y |
| Silent disconnect | 100 dead subs, no FIN | reaped within 3 heartbeats (~3 s) | Y once heartbeat added |
| Malformed | NaN coords from upstream override | rejected at boundary, counter ↑, no emit | Y once finite-float assert added |
| Malformed | unknown `kind` | 400 at HTTP, never reaches worker | Y once boundary validation added |
| Black swan | producer + slow sub + GC pause concurrent | worker_stall surfaced, no deadlock, no unbounded queue | requires watchdog + heartbeat |

## 9. Hand-offs

- P0/P1 fragility removals → **engineer** (small, mechanical).
- Antifragility wiring (adaptive cap, heartbeat reap, drift alert) →
  **Hamilton** (graceful degradation is his domain).
- Burst/disconnect/malformed bench harness → **Curie**.
- Worker-stall watchdog formal argument → **Dijkstra/Lamport** (fits
  their existing single-producer happens-before chain).
- Producer-drift policy (skin-in-the-game on the upstream) →
  **Coase** (transaction-cost framing of who pays for malformed input).
