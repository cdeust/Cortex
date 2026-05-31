# Beer VSM Audit — Cortex Layout Authority

Diagnostic frame: Stafford Beer's Viable System Model. The layout authority
must remain *viable* — adaptive, autonomous, coherent — under bursty,
unbounded producer load and lossy SSE consumers. This audit checks
structural completeness, variety balance, recursive viability, and
algedonic signal design.

## System boundary

- Inside: `layout_authority_geometry.py`, `_scheduler.py`, `_log.py`,
  `_protocol.py`, `_wire.py` (the five-module authority), plus the
  unread reference `layout_authority.py` that wires them.
- Environment: build worker (producer of NodeDelta/EdgeDelta), SSE
  subscribers (browser renderers), HTTP transport, viewport-driven
  `request_subtree` callers.
- Recursive level: L=0 = layout authority; L=+1 = Cortex MCP server
  (handlers + DB + transport); L=−1 = each per-priority queue inside
  the scheduler.

## Five-system audit

| System | Function | What fills it | Status | Channel integrity |
|---|---|---|---|---|
| S1 Operations | Closed-form O(1) slot computation per node | `layout_authority_geometry.py` (8 placement helpers + dispatcher) | Present, well-formed | Pure functions; no side channel; safe |
| S2 Coordination | Anti-oscillation + scheduling among ops | `layout_authority_scheduler.py` (7-level priority deque, P6 coalescing, single producer/consumer condvar) | Present, well-formed | `submit`/`pop`/`coalesce_subtree` mutually exclusive under one lock |
| S3 Resource bargaining | Internal "now" — cap allocation, drop accounting, fan-out | `_scheduler.QUEUE_SIZES` + `_log.emit/_fan_out/_reap` | Present but **distributed across two modules without an explicit S3 broker** | Stats are exposed but no module *decides* between log-buffer pressure and queue pressure |
| S4 Intelligence | Environment scanning, future modeling | `_scheduler.stats()`, `_scheduler.is_overloaded()`, `_log.stats()` | **Partial** — scanning capacity present, no forecasting; no sensor for *consumer* lag (subscriber miss-counters live inside `_log` and never escape) | Read-only `stats()` endpoints exist; no closed-loop feedback to S5 |
| S5 Policy / Identity | Defines what the authority IS; balances S3↔S4 | `_protocol.py` (NODE_KINDS, EDGE_KINDS, INVARIANTS I1–I7, `LayoutAuthority` Protocol) | Present, **strong** — invariants are normative and cited at refs in code | Invariants are documented but compile-time only; no runtime enforcer module monitors all seven |

**Verdict:** S1, S2, S5 are fully present and structurally sound. S3 is
*malformed-by-distribution*: the resource-bargaining function is split
between scheduler caps and log fan-out without a single broker that can
trade off between them under joint pressure. S4 exists as passive
sensors but has no analyser that turns them into a forecast or a policy
update. This is the textbook Beer pathology of "sensors without a head."

## Variety analysis

| Interface | Environmental variety | System variety | Gap | Remedy |
|---|---|---|---|---|
| Build worker → authority | Unbounded burst (1e9 events theoretical, design assumes 1e6/build) | 7 priority queues, caps 1k…128k, total ~243k pending | Attenuate (already done): drop-by-priority is a *variety attenuator* — `submit` shed at cap | Sufficient for documented load; cite the cap derivation |
| Authority → SSE subscribers | One slot event must paint many pixels across N viewers | `_log._fan_out` snapshots the subscriber list and pushes once per subscriber | **Amplify** — one S1 event explodes into k subscriber deliveries | Verified: O(1) auth-side, O(k) deliver-side; bounded by `_DEAD_QUEUE_MISS_THRESHOLD=200` reaping |
| Viewport drag → request_subtree | ~10 req/s per active viewer | P6 coalescing dedupes per `domain_id`; cap 100 | Attenuate | Sound — coalescing is the right move |
| Wire encoder | UTF-8 strings of variable length | Pipe-delimited fixed-shape, validated against `|`, `\n`, `\r` | Attenuate | Sound — `_validate_id`/`_validate_kind` reject pathological inputs |
| Subscriber backpressure | Slow client drains <100k/sec sustained | Auto-eviction at 200 consecutive misses | Attenuate (drop the consumer, not the producer) | Sound — preserves Hamilton invariant |

**Variety drops in scheduler are correct attenuators**: P5 edges shed
before any node, P4 symbols shed before structural nodes, P0 domains
*never* shed in practice. **One S1 → multi-pixel paint** is the canonical
amplifier and is implemented correctly via fan-out + chunked SSE.

## Recursive viability

| Subsystem | Own S1–S5 complete? | Missing systems | Consequence |
|---|---|---|---|
| `_geometry` (L=−1) | Trivially viable — pure function, no environment to be viable in. | — | Bottom-out point of recursion. Correct. |
| `_scheduler.PriorityScheduler` (L=−1) | S1 = deques; S2 = condvar; S3 = caps; S4 = `stats`/`is_overloaded`; **S5 absent** — no module-internal policy that tunes caps from observed drops | S5 | Caps are static. A sustained P4 overflow cannot raise its own cap or shed P5 *more aggressively*. The decision rests with the human operator. Acceptable at L=−1 if the parent (L=0) has S5 to compensate. |
| `_log` (L=−1) | S1 = ring buffer; S2 = single-producer rule (load-bearing per docstring); S3 = caps + reap; S4 = `stats`; S5 absent | S5 | Same: log cap is static. |

**Does the authority itself fit inside a higher-level VSM (the Cortex
MCP server)?** Yes, but the seam is thin:

- L=+1 S1 ≈ MCP tool handlers (33 of them); the layout authority is one
  S1 unit among many.
- L=+1 S2 ≈ FastMCP transport + `tool_registry_*` dispatch.
- L=+1 S3 ≈ `infrastructure/memory_config.py` + connection pools.
- L=+1 S4 ≈ `core/metacognition.py`, benchmarks, `assess_coverage`.
- L=+1 S5 ≈ project `CLAUDE.md` + `docs/adr/`.

The authority is a viable S1 unit at the parent level **iff** its
algedonic signals reach parent S3/S4. They do not (see below).

## Autonomy–cohesion map

| S1 unit | Current autonomy | Cohesion constraints (S3) | Balance assessment |
|---|---|---|---|
| `_geometry.compute_slot` | Full — pure dispatch | Match `workflow_graph.js` constants verbatim | **Correct.** Autonomy is bounded by an external visual contract; the cohesion is enforced by the comment trail and tests. |
| `_scheduler` | Full — owns its caps and drop logic | `Stats` must be readable by S4 endpoints | **Correct.** |
| `_log` | Full — owns ring buffer and subscriber list | Single-producer rule (docstring) | **Fragile cohesion.** Single-producer is *documented* but not *enforced*. Two callers of `emit()` from different threads silently violate I1/I2 ordering. |
| `_wire` | Full — owns encoding | Must reject `|`, `\n`, `\r` | **Correct.** Defense-in-depth at the boundary. |

## Algedonic signals

| Signal | Source | Threshold | Destination | Filterable? | Status |
|---|---|---|---|---|---|
| Queue overflow → `Stats.dropped[p]++` | `_scheduler.submit` cap-reject | Implicit (cap exceeded) | `stats()` snapshot | **Filterable** — only surfaces if someone polls | **Weak.** No push channel from scheduler to S4/S5. |
| `is_overloaded(threshold=0.8)` | `_scheduler` | 80% of any cap | Caller of `is_overloaded` | **Filterable** — must be polled | **Weak.** Threshold-based but pull-not-push. |
| Subscriber dead → reap | `_log._fan_out` after 200 misses | 200 consecutive `put_nowait` failures | Local reap in `_reap` | **Unfilterable internally** but never propagates upward | **Weak.** Producer learns nothing about chronic subscriber slowness. |
| Replay-lost gap | `_log.replay_since` returns gap | `since < oldest_seq − 1` | SSE handler emits `replay_lost` sentinel; client falls back to snapshot | **Unfilterable** — gap detection is automatic | **Strong.** This is the one true algedonic channel — automatic, threshold-based, surfaces at the wire. |
| Invariant violation (I1–I7) | None — documentation only | n/a | n/a | n/a | **Absent.** The strongest S5 statement in the codebase has no runtime monitor. |

## Structural prescriptions

| Gap | Required function | Predicted failure if unaddressed | Priority |
|---|---|---|---|
| S3 broker absent | A single module that owns *both* scheduler caps and log cap, can shed P5 harder when log buffer is full, and exposes one back-pressure number | Under joint burst (huge build + slow subscriber), the system will silently drop wire events while still admitting new node deltas; the SSE stream goes inconsistent without operator visibility | **High** |
| S4 forecast absent | A small analyser that reads `_scheduler.stats()` + `_log.stats()` periodically, computes drop-rate trend, and tags the build as "degraded" | The build completes and reports `done` totals that *disagree* with what the client received, with no flag | **High** |
| Invariants I1–I7 unenforced at runtime | An assertion module that verifies seq monotonicity (I2), parent-before-child for symbols (I3), domain reachability (I7) on every emit; opt-in for prod, default-on for tests | Quiet violation under reordering; client-side rendering NaN or floating "orphan" symbols at wrong anchor | **High** |
| Single-producer rule unenforced | `_log.emit` records calling thread on first call and asserts on subsequent threads | Two threads emit interleaved, fan-out delivery order disagrees with seq order, client SSE replay violates I2 | **Medium** |
| Algedonic push channel | A bounded "alarm" queue (priority −1) that the scheduler/log fill on threshold crossing; SSE wire emits a synthetic `degraded` event the renderer can surface | Operator only sees overload via manual polling of stats endpoint | **Medium** |
| Recursive S5 at L=−1 | None — accept that L=−1 modules borrow S5 from L=0; document it explicitly so caps are tuned from L=0 only | Without docs, future maintainers will add ad-hoc cap-tuning logic *inside* `_scheduler` and break locality | **Low** |

## Hand-offs

- Feedback dynamics analysis (drop-rate as control variable; oscillation
  risk between cap-tuning and load) → **Meadows**.
- Overload / graceful-degradation design (the S3 broker spec; threshold
  curves) → **Hamilton**.
- Implementation of S3 broker, runtime invariant enforcer, algedonic
  push channel → **engineer**.
- Measurement of drop-rate distributions, replay-lost frequency,
  subscriber-eviction rate under realistic builds → **Curie**.

## Verdict

The authority has S1, S2, S5 of textbook quality. S3 is structurally
**distributed without a broker** — viability holds today only because
load fits within static caps. S4 has sensors but no analyser. The
algedonic surface is dominated by **pull** signals; only `replay_lost`
is a true Beer-grade unfilterable threshold signal. Under sustained
joint pressure (large build + slow subscriber + viewport drag) the
system will degrade silently. The remediations above are necessary for
viability at L=+1 (the MCP server treating the authority as a black-box
S1 unit must be able to *hear* its pain).
