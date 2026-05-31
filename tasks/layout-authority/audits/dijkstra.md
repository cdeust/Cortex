# Dijkstra Audit — `layout_authority.py` Correctness Obligations

Scope: the consolidated `mcp_server/server/layout_authority.py` wiring
`_protocol`, `_geometry`, `_scheduler`, `_log`, `_wire`. What follows
must be **proved or defended**; tests supplement, do not replace, the
argument. Stakes: **High** — concurrency, bounded-state under unbounded
arrival, client-observable ordering. Local reasoning across module
boundaries is mandatory.

## 0. Pre-flight contract defects (resolve before integration)

- **D0 — Field-name mismatch.** `_protocol.SlotAssignment.node_id`;
  `_wire.format_slot` reads `slot.id`. Protocol is normative — fix
  `_wire`. Without this, integration cannot type-check.
- **D1 — Single-producer rule is implicit.** `_log.emit` documents it
  in prose only. Integration must enforce structurally: ONE worker
  thread pops `_scheduler` and calls `emit`. Otherwise H1/H2 break.
  Add thread-id assertion at `emit` entry.
- **D2 — `_log` is module-global state.** Two authorities in one
  process share log + seq. Either declare "one authority per process"
  as construction precondition (assert at build time), or refactor
  `_log` to instance state. Default-refuse module globals (§7.2 of
  coding standards) requires explicit ADR if kept.

## 1. Entry-point pre/postconditions

**`add_node(delta)`** — *Pre:* `kind ∈ NODE_KINDS`; ids non-empty,
delimiter-free (`|`, `\n`, `\r`) at protocol boundary not deferred to
`_wire`; per-kind constraints from `NodeDelta`; `kind=='domain' ⇒
domain_id==node_id`. *Post:* non-blocking; either submitted at
`priority_for_node(kind)` OR dropped+counter (never both, never
neither); EXACTLY ONE `SlotAssignment` emitted in bounded time iff
parent state present (I3/I4/I7), else buffered. *Test:* Pre raises
`ValueError`; property — any valid arrival order ⇒ one slot per
accepted node_id.

**`add_edge(delta)`** — *Pre:* `kind ∈ EDGE_KINDS`; ids non-empty,
delimiter-free. *Post:* non-blocking; pushed to P5, buffered (I5), or
dropped+counter; ZERO slots emitted; `'edge'` event in bounded time iff
both endpoints present. *Test:* assert slot counter unchanged on
`add_edge`; buffered edges flush within K events of second endpoint.

**`request_subtree(domain_id)`** — *Pre:* non-empty. *Post:* idempotent
+ coalesced (N back-to-back calls ⇒ ≤1 P6 entry); on service, re-emit
with strictly higher seq than prior (I2). *Test:* coalesce assertion;
seq strict-increase.

**`subscribe()` / `unsubscribe(q)`** — *Post (sub):* queue registered
before return; any `emit()` after return delivers to it. *Post
(unsub):* idempotent; no delivery *initiated* later goes to `q`;
in-flight from concurrent fan-out snapshot is permitted. *Test:* stress
with rapid sub/unsub under load.

## 2. Happens-before: `add_node → slot emission → SSE write`

Chain (single worker):

```
producer:  add_node(N) → scheduler.submit(prio, item)        [HB-0]
worker:    pop() → compute_slot → wire.format_slot
           → log.emit:
              under _event_log_lock: seq += 1; append        [HB-A]
              release lock
              _fan_out: snapshot subs under _subscribers_lock [HB-B]
                        for each q: q.put_nowait(event)      [HB-C]
SSE thread: q.get() happens-after HB-C for that q
           → socket.send
```

- **H1 — Seq strict-monotonic per instance.** `+=` and `append` under
  one lock; single worker calls `emit`. *Argument by construction.*
  Verify: assert `seq == _event_log[-1][0]` in `emit`; multi-priority fuzz.
- **H2 — Per-subscriber delivery order = seq order.** Single producer
  + FIFO `queue.Queue` ⇒ preserved. Broken if two threads call `emit`.
  Verify: thread-id assertion at `emit` entry; chaos test with second
  emitter confirms assertion fires.
- **H3 — `_fan_out` snapshot semantics.** Subs added during fan-out
  may or may not see in-flight event; subs removed may still see it
  (reap is post-fan-out). Acceptable iff `unsubscribe` doesn't promise
  "no more events" (it doesn't).
- **H4 — Parent-before-child for symbols (I3).** P2 (file) < P4
  (symbol) ⇒ strict-priority drains files before symbols. Symbols
  arriving before parent's `add_node` ⇒ parent-pending buffer keyed by
  `parent_id`, flush on parent emit. Bounded; overflow drops+counter.
  Verify: arrival-permutation property test; assert no symbol slot
  before its parent file's.
- **H5 — Edges happen-after both endpoint slots.** Same I5 pattern.
  Client renders edges between known nodes; pre-endpoint emit dangles.

## 3. Bounded state under sustained 10⁶ events/sec

Cost-model says ≤10 ns/node at 10⁹ in 1–2 s; pure-Python bench is
180–300 ns/slot. At sustained 10⁶/sec arrival, **the worker cannot
keep up in pure Python** — the scheduler fills and sheds by design.

- **B1 — Scheduler residency ≤ Σ(QUEUE_SIZES × ~80B) ≈ 19.4 MB
  worst-case** (`_scheduler` docstring). **Exceeds 8 MB cost-model
  ceiling.** Engineer picks one: (a) shrink P5 cap (edges alone =
  10.2 MB); (b) ADR that 8 MB is non-burst steady-state; (c) bench
  residency <8 MB under 10⁶/sec. Verify: `tracemalloc` every 100 ms
  for 60 s; report max delta + per-priority drop rates.
- **B2 — Event log = 500k × ~80B ≈ 40 MB.** Only structure scaling
  with stream length. Defend in ADR or shrink. Verify: assert
  `len(_event_log) ≤ _EVENT_LOG_CAP`; bench RSS plateau.
- **B3 — Subscriber queues = 100k × N_subs.** Steady-state bounded by
  drain rate iff reaping fires. Show: (a) SSE drain ≥ producer emit at
  10⁶/sec, or (b) reaping fires within 200-miss window before queue
  residency dominates. Verify: slow-subscriber bench; assert reap.
- **B4 — Pending-edges (I5, 100k) + parent-pending (32k by analogy
  with P3) bounded; overflow drops+counter.** Verify: fill test.
- **B5 — Per-domain counters O(domains × kinds), ~528 B for 11×6.**
  Linear in `n_domains`; hard cap (e.g. 1000) or ADR.
- **B6 — No per-event allocation growth.** `_wire` constants
  pre-encoded; `format_slot` is O(1). `tracemalloc` 1M events; assert
  linear, no leak.

## 4. Deadlock freedom across `event_log_lock` and `subscribers_lock`

- **D1 — Strict never-nested order in `emit`.** Releases
  `_event_log_lock` BEFORE `_fan_out` takes `_subscribers_lock`; never
  held simultaneously. Argument by code reading; debug thread-local
  "held set" asserts empty before each acquire.
- **D2 — No re-entrancy.** `emit` calls no function that calls `emit`;
  `_fan_out` calls only `q.put_nowait` (queue-internal). Textual.
- **D3 — Scheduler lock disjoint.** `_scheduler._lock` held only in
  scheduler methods, none of which call into `_log`. Worker pops, then
  releases, then emits.
- **D4 — `q.put_nowait` non-blocking.** Full ⇒ Full exception, caught.
  Subscriber backpressure cannot deadlock producer.
- **D5 — `_log.reset()` takes both locks (event_log first, then
  subscribers).** If any other path reverses, AB/BA deadlock possible.
  Engineer audits: no other path takes both, or enforces same order
  everywhere. Lockdep instrumentation in debug.
- **D6 — External callers must not hold their own lock when calling
  `emit`/`subscribe`.** API-boundary contract; watchdog test that
  violates it and asserts timeout fires.

## 5. Testing coverage vs. required argument

| Property | Testable | Beyond tests |
|---|---|---|
| Entry-point Pre/Post | yes | body assertions |
| I1 finite floats | yes | property test on `compute_slot` |
| I2 seq monotonic | partial | + single-producer thread-id assertion |
| I3/I4/I7 parent-first | partial | + single-worker construction argument |
| I5 bounded buffers | yes | overflow test |
| I6 non-blocking submit | partial | bench + `submit` code argument |
| Bounded state under load | **no** | instrumented bench + cap argument |
| Deadlock freedom | **no** | static lock-order proof; lockdep DiD |
| Happens-before chain | partial | thread-id + single-producer argument |
| 10⁶/sec sustained | yes (bench) | max RSS, drop rates, p50/p99 latency |

**Dijkstra's rule applies in full.** Properties marked **no** or partial
must be argued, not tested-into-existence. Engineer's `derivation.md`
must contain explicitly: the lock-order argument (§4), the
single-producer argument (H1/H2), the bounded-state argument (§3).

## 6. Compliance (coding-standards.md)

- §1.1 SRP — PASS iff `layout_authority.py` is placement coordination
  only (no detection/persistence/HTTP).
- §2.2 layers — `_protocol` contract-only; `_geometry` pure;
  `_scheduler`/`_log`/`_wire` stdlib-only; this file is composition
  root. PASS.
- §4.1 ≤500 lines — likely needs split (worker loop, parent-pending,
  pending-edges).
- §7.2 default-refuse module globals — `_log` triggers; ADR (D2) or
  refactor to instance state.
- §8 sources — `_geometry`↦`workflow_graph.js`; `_scheduler`↦Hamilton
  1969; `_wire`↦Shannon. PASS.

## 7. Hand-offs

- D0 field-name fix, single-producer enforcement, `_log` instance-state
  refactor → **engineer**.
- Bounded-state defense at 10⁶/sec, RSS budget → **engineer + Curie**.
- Lock-order formal proof beyond static argument → **Lamport** (TLA+)
  if desired; otherwise lockdep instrumentation suffices.
