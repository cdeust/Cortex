# Boyd OODA Audit — Layout Authority Overload Behavior

**Frame:** the Hamilton scheduler shed work tactically (drop P4/P5 first, never block P0). That is correct mechanics. The strategic question is whether the authority can complete an Observe-Orient-Decide-Act cycle on its own overload faster than the upstream build worker can saturate it. If the loop is slower than the threat, no amount of priority discipline rescues the system — it just fails politely.

**Verdict:** the OODA loop is **anatomically incomplete**. Observe primitives exist; Orient is missing; Decide is binary and silent; Act has no channel back to the producer. The authority cannot get inside its own threat's loop.

---

## 1 — Observe: primitives exist but most are unread

| Signal | Source | Read by? | Latency to surface |
|---|---|---|---|
| Per-priority queue length | `PriorityScheduler.stats()["lengths"]` | `/api/layout/stats` (poll) | only on poll |
| Per-priority drops (cumulative) | `Stats.dropped` | `/api/layout/stats` (poll) | only on poll |
| Aggregate overload boolean | `is_overloaded(0.8)` | **NO PRODUCTION CALLER** (`grep` confirms) | never surfaced |
| Event-log drops | `_event_log_drops` (module global) | only `stats()` snapshot; **no test of production read path** | only on poll |
| Subscriber miss count | `q._cortex_misses` (per-queue attr) | `_fan_out` only, for reaping | never exported |
| Subscriber dead-eviction events | (no counter) | nobody | invisible |

**Boyd reading:** observation channel is bytes-rich and event-poor. Drops are stored as monotonic counters that a poller has to *differentiate against time* to recover a rate. By the time a poll-driven dashboard sees `dropped[P4]` rising, the burst is already over and the symbols are already gone. This is observation in the wrong representation — Boyd's "orient on yesterday's state" failure mode at the metrics layer.

**Concretely missing:**
- No edge-triggered "overload entered" / "overload exited" event on the SSE log itself.
- No first-derivative metric (drops/sec, queue-depth slope).
- `is_overloaded()` returns a bare bool — no field naming WHICH queue saturated, so even if someone called it they couldn't orient on cause.

---

## 2 — Orient: the critical phase is missing entirely

The strategic question — *why* are we overloaded? — has no module that answers it. Possible causes:

1. **Slow SSE client** — one subscriber's queue is filling, fan-out is blocking nobody (it's `put_nowait`), but the client still consumes events the build worker generates. **Producer keeps going.** This actually does NOT cause scheduler overload; it causes log-drop & subscriber reaping.
2. **L6 symbol burst** — build worker emits 500k symbols faster than the layout engine drains P4. Scheduler's P4 deque saturates at 64k → drops cascade.
3. **Subscriber backed up but log drops** — `_event_log` ring overruns its 500k cap; `_event_log_drops` ticks; replay-since-N starts returning the gap sentinel; clients fall back to snapshot. Producer is unaffected.
4. **Coalesced P6 storm** — viewport drag firing recomputes; `coalesce_subtree` saves the queue but each pop re-runs an expensive recompute that starves P0-P5 drain.

Each of these has a **different correct mitigation**. The system today cannot tell them apart. There is no module that takes `(queue_lengths, drops_per_priority, log_drops, subscriber_misses)` and emits a typed orientation `{cause: SLOW_CLIENT | SYMBOL_BURST | LOG_OVERRUN | RECOMPUTE_STORM, evidence: ...}`. Without that, every overload looks the same and every response is the same: "drop P4 first." That is correct only for cause #2.

**Self-referential trap:** the only on-line orientation primitive is `is_overloaded(0.8)`. It synthesizes nothing — it's just `any(q >= 0.8*cap)`. The orientation IS the observation, repackaged. Boyd would call this a degenerate orientation phase: the model has been replaced by a passthrough.

---

## 3 — Decide: binary, implicit, no policy surface

The current decision policy is encoded structurally, not behaviorally:
- "If queue full → drop." (in `submit`)
- "If subscriber misses > 200 → reap." (in `_fan_out`)
- "If log full → overwrite oldest, increment counter." (in `emit`)

There is **no decision module** that, given an orientation, selects among:
- Drop P4 / drop P5 / drop both.
- Throttle the producer (no channel exists — see §4).
- Broadcast a `degraded` SSE event so clients render a "partial graph" badge.
- Coalesce harder (raise P6 dedup window).
- Trip a circuit-breaker on `request_subtree`.

These are all viable mitigations for *different* causes. The authority commits to exactly one (drop in priority order) regardless of cause. **Schwerpunkt failure**: maximum effort is concentrated at the symptom (full queue) not at the decisive point (whichever upstream behavior produced the burst).

---

## 4 — Act: no closed feedback to the build worker

This is the load-bearing finding. Search across `mcp_server/` for any path from the scheduler / log back to the producer:

- `submit()` returns `False` on drop. **Nobody surfaces that boolean to the build worker** — the worker emits via the same `emit()`/`submit()` path and never reads back.
- `is_overloaded()` is unread. There is no `/api/layout/backpressure` endpoint, no SSE `degraded` event, no shared `Event` flag the build worker waits on.
- The SSE event vocabulary is `{slot, edge, done}`. There is no `degraded`, no `overloaded`, no `dropped_since_seq=N` event. Clients cannot even *display* that the graph they're seeing is incomplete.

**Consequence:** the build worker runs open-loop. When the authority is saturated, the worker is saturating it MORE, not less. The OODA loop has no Act phase that touches the threat. The threat is the producer; the response is internal triage; the producer never learns. This is the textbook condition Boyd describes for a system whose adversary's tempo exceeds its own — except the "adversary" here is its own upstream.

---

## 5 — Tempo verdict

| Phase | Latency to complete | Bottleneck |
|---|---|---|
| Observe | poll-interval (~1s typical) | poll-driven, not edge-driven |
| Orient | 0 — phase missing | no synthesis module |
| Decide | 0 — hardcoded structurally | no policy surface |
| Act | ∞ — no producer-facing channel | structural absence |

Build worker can saturate P4 (64k) with a symbol burst in **a single emit batch** at ~1µs per submit ≈ 64ms. The authority's slowest-case detection latency is the dashboard poll interval, ~1000ms. **The producer is ~15× faster than the detection loop**, and the response loop doesn't terminate at all because there is no Act channel back. Boyd's necessary condition (OODA tempo ≥ threat tempo) is violated by more than an order of magnitude.

---

## 6 — Schwerpunkt: where to concentrate effort

Of the four anatomical gaps (Observe-rate, Orient, Decide-policy, Act-channel), **the decisive point is the Act channel.** Reasoning:

- Observe is adequate-once-edge-triggered: turn `is_overloaded` transitions into SSE events. Cheap.
- Orient can stay coarse for now: tag the cause with the dominant saturated priority (one-line classifier). Cheap.
- Decide can stay coarse: a 3-row policy table keyed on cause. Cheap.
- **Act has no infrastructure at all.** Without it, all upstream improvements are observation-quality theater. The build worker keeps running open-loop.

Act sub-points, ordered by leverage:
1. SSE `degraded` event with `{cause, dropped_counts, since_seq}` — clients can render correctly.
2. Cooperative back-pressure: build worker reads a shared `threading.Event` (`_overloaded_flag`) before emitting each L6 batch and yields if set. No new IPC; same process.
3. `/api/layout/backpressure` endpoint returning the current orientation — for out-of-process producers later.

(1) and (2) close the loop today with <50 LoC each.

---

## 7 — Destructive deduction of the current model

Decompose the implicit mental model behind the current code:

| Assumption | Verified? |
|---|---|
| "Producer never blocks" (Hamilton invariant) | yes — by construction in `submit` |
| "Drops in priority order preserve topology" | yes — for cause #2 only |
| "Drops are rare enough that observability via poll is sufficient" | **unverified** — no measured drop-rate budget |
| "The producer cannot react, so we shouldn't bother signaling" | **false** — same-process; trivially can |
| "All overload causes are equivalent" | **false** — at least 4 distinct causes |
| "`is_overloaded` is useful as defined" | **false** — unread, undifferentiated, unevented |

Recombine into a corrected model: *"Producer never blocks, but producer SHOULD voluntarily yield on a flagged overload; drops are typed by cause; cause is broadcast on the same channel as the data so clients orient on the same model the server does."*

---

## 8 — Recommendations (Boyd-prioritized)

1. **Schwerpunkt — close the Act channel.** Add `_overloaded_flag: threading.Event` set/cleared by the scheduler on `is_overloaded` transitions. Build worker consults it between L6 batches. (≤30 LoC, removes the order-of-magnitude tempo gap.)
2. **Edge-trigger Observe.** Emit `degraded` and `recovered` SSE events at the transitions. Stops poll-blindness for clients. (≤40 LoC.)
3. **Type the orientation.** One classifier function `classify_overload(stats) -> Cause` keyed on which priority crossed first. Rejects the "all overloads identical" trap. (≤25 LoC.)
4. **Surface `_event_log_drops` and subscriber-eviction counts on `/api/layout/stats`.** They exist; export them. Free.
5. **Bounded recompute storm guard.** P6 already coalesces by id; add a per-domain min-interval (e.g. 250ms) so a held viewport drag cannot generate one expensive recompute every pop.

Items 1–3 are the loop. Item 4 is hygiene. Item 5 closes the one cause currently invisible to the priority scheme.

## 9 — Hand-offs

- **Hamilton** — already owns the priority-displaced scheduler. No change to his invariant; the Act channel is additive.
- **Shannon** — quantify the Observe channel: drops/sec budget, false-positive rate of the `is_overloaded(0.8)` threshold.
- **Lamport** — formalize the happens-before of `degraded` event vs. dropped slot delivery, so a client that receives `degraded` knows whether to discard or render in-flight slots.
