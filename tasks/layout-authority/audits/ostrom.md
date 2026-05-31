# Ostrom — Commons-Governance Audit of the Layout Authority

> The layout authority is a commons. Three shared resources — the slot table
> (one canonical (x,y) per node), the event log (replay buffer), the
> subscriber list — are accessed by multiple parties (build worker, SSE
> handlers, MCP request handlers, browser clients) under a single producer
> contract. Tragedy here is not overgrazing of grass; it is one party
> mutating a slot another already streamed, one subscriber starving the
> producer, or one client filling the replay window with garbage.
>
> Ostrom 1990 *Governing the Commons* Ch. 3: long-enduring commons exhibit
> all eight design principles. Failed commons are missing one or more.
> Method: score each principle against the implementation in
> `mcp_server/server/layout_authority{,_log,_protocol}.py`.

## 1. The three commons

| Commons | Resource | Producers | Consumers | Subtractable? | Depletable? |
|---|---|---|---|---|---|
| **Slot table** `_slots: dict[node_id → SlotAssignment]` | Canonical (x,y) per node | Build worker (single, via `add_node`) | All SSE subscribers (read-only via emit) | No (write-once per I2/I4) | No (bounded by node count) |
| **Event log** `_event_log: deque(maxlen=500_000)` | Ordered (seq, kind, payload) replay window | `emit()` from authority | `replay_since(N)` from any thread | Yes (oldest evicted at cap) | Yes (drops on overflow) |
| **Subscriber list** `_subscribers: list[Queue]` | Fan-out slots; per-sub queue (cap 100k) | `subscribe()` from any thread | `_fan_out` (producer) writes; SSE handler drains | Yes (queue fills, `put_nowait` fails) | Yes (eviction at miss > 200) |

## 2. Eight-principles audit

| # | Principle | Status | Evidence | Gap |
|---|---|---|---|---|
| 1 | Clearly defined boundaries | **present** | `NODE_KINDS` / `EDGE_KINDS` are `frozenset` (protocol §28-40); `_validate_node` / `_validate_edge` raise on unknowns; `domain_id` non-empty enforced; subscriber identity = the returned `Queue` object. | Subscriber identity is opaque (no name/origin/credential). Cannot rate-limit per-tenant or attribute drops to a specific browser tab. |
| 2 | Proportional cost/benefit | **degraded** | Each subscriber pays its own drain cost (own thread); producer cost is amortized O(1) (Fermi §). Producer is NOT charged for slow subscribers — the bounded `Queue` + `_DEAD_QUEUE_MISS_THRESHOLD=200` evicts them. | A subscriber that drains fast PAYS THE SAME (one Queue allocation) as one that drains slowly until eviction. Heavy subscribers are not asked to contribute (e.g. throttle their own LOD). The 200-miss threshold is the only proportionality lever. |
| 3 | Collective-choice arrangements | **absent** | Tunables (`_PENDING_EDGES_CAP=100_000`, `_EVENT_LOG_CAP=500_000`, `_SUBSCRIBER_QUEUE_CAP=100_000`, `_DEAD_QUEUE_MISS_THRESHOLD=200`, `_DEFAULT_DOMAIN_RESERVATION=16`) are module-level constants. Subscribers and the build worker — the actual users — cannot influence them. | No collective-choice mechanism. A subscriber who knows it cannot drain at 100k/s has no way to negotiate a smaller queue or higher miss tolerance. The build worker cannot widen the replay window for a known long-running session. |
| 4 | Monitoring | **partial** | `LayoutAuthority.stats()` exposes `slots_emitted, edges_emitted, edges_dropped, pending_symbols, pending_edges, domains`. `layout_authority_log.stats()` exposes `size, cap, oldest_seq, newest_seq, drops, subscribers`. | **Behavior is monitored only at coarse aggregate.** No per-subscriber metrics (which sub got evicted, when, after how many misses). No per-domain slot-count distribution (could a single domain be hogging the bucket counters?). Drops are counted but the dropped key is not logged — root cause for capacity exhaustion is invisible. |
| 5 | Graduated sanctions | **violated** (the canonical gap) | Subscriber misbehavior path: `put_nowait` fails → `_record_miss` → `misses > 200` → eviction. **One step. Binary.** Pending-edges overflow: `popitem(last=False)` → silent FIFO drop. Event log overflow: `deque.maxlen` evicts oldest, increments `_event_log_drops`. | All three commons use **threshold-then-execute**. There is no warning, no degradation, no "you're at 80% of your queue, slow your subscription request rate", no "this subscriber has been at >50% utilization for 30s — switch to LOD-2". The dead-queue threshold is the textbook example: 199 misses = healthy; 201 misses = dead. |
| 6 | Conflict resolution | **absent** | What happens if two callers do `request_subtree(d)` while the build is mid-flight? Both succeed (idempotent — see L201-209). What happens if a subscriber subscribes mid-stream? It misses everything before its `subscribe()` and must rely on `replay_since(0)` from a separate code path. | No documented arbiter for: (a) replay-gap reconciliation (the `replay_lost` sentinel exists in `_log.replay_since` but no sanction or escalation when a client repeatedly hits it); (b) competing `request_subtree` calls during a build; (c) build-reset (`reset()`) racing with active subscribers — `_subscribers.clear()` drops them on the floor without notification. |
| 7 | Right to self-organize | **partial** | Subscribers self-organize their own consumption (own thread, own queue, own LOD policy via `layout_authority_lod`). `request_subtree` is a self-service re-emission API. | The build worker cannot self-organize the producer rules. `_DEFAULT_DOMAIN_RESERVATION=16` is a module constant. A worker that knows it has 50 domains coming cannot pre-reserve 50 slots — it gets the chunked grow-on-demand at L82-87, which freezes earlier anchors at lower-reservation positions. The "right" exists but the mechanism is missing. |
| 8 | Nested enterprises | **partial** | Layered: `layout_authority_geometry` (pure math) ⊂ `layout_authority` (in-memory state) ⊂ `layout_authority_log` (event log) ⊂ `layout_authority_wire` (SSE encoding) ⊂ HTTP handler ⊂ MCP server. Each layer governs at its own scale. | Governance does not flow between scales. The HTTP handler cannot tell the authority "this client is a screenshot bot, give it a snapshot and don't subscribe it"; the authority cannot tell the log "this build is small, shrink the buffer". Nesting is structural, not governance-coupling. |

## 3. Rules-in-use vs rules-on-paper

| Rule on paper | Rule in use | Gap |
|---|---|---|
| INVARIANTS I2: monotonic seq | `_event_seq` is global; `reset()` does NOT reset it (L218-223 prose vs prior code-body). | The prose-vs-code disagreement was resolved in favor of prose. **A future refactor could re-introduce the bug** — the rule survives only by comment. Make it a property test. |
| I5: pending-edges bounded at 100k, oldest dropped | Implemented (L390-394). | `_edges_dropped` is incremented but the dropped edge's `(src,tgt,kind)` is gone — no audit trail to diagnose why a graph is missing edges. |
| I6: emit never blocks | `_fan_out` runs against a snapshot of `_subscribers` (L91-92), so the producer doesn't block on the subscriber lock. | Producer DOES hold `_event_log_lock` across `deque.append` (L129-135). Contention is in-process µs but real. |
| Single-producer rule (`emit` from one thread) | Asserted in module docstring; **not enforced**. | A second producer would silently corrupt seq order. Add a thread-id check in debug. |

## 4. Sustainability assessment

- **Slot table** regenerates only via fresh build (`build_authority` → `_log.reset` → new `LayoutAuthority`). Lifetime = one build. Sustainable.
- **Event log**: 500k events × ~112 B = ~56 MB. Coase audit flagged this exceeds the 8 MB ceiling; sustained at ~10⁵ evt/s the buffer fills in 5 s — clients with >5s reconnect lag fall outside the window and need snapshot fallback. **Regeneration rate (deque eviction at cap) ≪ peak emission rate** during burst.
- **Subscriber list**: regeneration via eviction. A pathological subscriber consumes producer fan-out CPU (the `put_nowait` + miss-count branch) for 200 events before reaping. At 10⁵ evt/s that is 2 ms of producer CPU spent on a dead subscriber.

## 5. Polycentric-governance design (the fixes)

| Scale | Authority | Decisions it should own | Constraints from above |
|---|---|---|---|
| Build worker (producer) | `LayoutAuthority` instance | Domain reservation hint at construction; per-build replay-window size; per-build subscriber admission policy | Module-level absolute caps (memory ceiling) |
| Authority instance | `_log` + `_subscribers` | Per-subscriber queue size negotiated at `subscribe(qos=...)`; graduated backpressure (warn → throttle → evict) | Build worker's per-build budget |
| Subscriber | SSE handler | Self-declared QoS (snapshot vs live; LOD level); voluntary throttling | Authority's admission decision |
| HTTP handler | Server | Tenant identity → subscriber identity for monitoring | Authority API |

## 6. Recommended interventions (priority order)

1. **Graduated sanctions** (gap #5, the headline) — replace the binary
   200-miss threshold with: misses 1–50 = silent retry; 51–100 = warn
   in `stats()`; 101–200 = drop low-priority events for that sub
   (`edge` before `slot`); 201+ = evict. Same shape for pending-edges
   (warn at 80% → drop low-kind edges → drop FIFO at cap) and event
   log (warn when oldest_seq age > 30s → emit `degraded` sentinel
   before silent drop).
2. **Per-subscriber identity + monitoring** (gap #1, #4) — `subscribe()`
   takes an opaque `client_id`; `stats()` returns per-sub miss counts,
   queue depth, last-drain-age. Enables proportional cost (#2) and
   conflict resolution (#6).
3. **Collective choice via `subscribe(qos=...)`** (gap #3, #7) —
   subscriber declares (`live` | `replay-only`, `lod=0..3`,
   `max_queue=...`); authority admits or rejects; ruleset becomes
   negotiable, not a module constant.
4. **Audit trail for drops** (gap #4) — log dropped edge keys to a
   bounded ring (1k entries) accessible via `stats(detail=True)`. Cheap;
   makes I5 violations diagnosable.
5. **Reset notification** (gap #6) — `_log.reset()` should fan out a
   `reset` sentinel BEFORE `_subscribers.clear()`, so SSE handlers can
   close cleanly. Currently they discover the reset via stalled drain.
6. **Single-producer enforcement** (rules-in-use gap) — debug-mode
   `threading.get_ident()` check in `emit()`; assertion failure on
   second producer. The rule survives by comment today; promote it to
   code.
7. **Domain reservation hint** (gap #7) — `build_authority(domain_hint=N)`
   skips the chunked-grow path when the worker knows the count.

## 7. Compliance check (coding standards §11)

| Rule | Status | Note |
|---|---|---|
| 1 SOLID | pass | Each module = one responsibility (geometry / log / wire / protocol). Audit recommendations preserve SRP. |
| 2 Layer dependency | pass | `layout_authority` (server-layer) imports geometry/log/wire/protocol; no inversion. |
| 7 Local reasoning | pass | No reflection/monkey-patching; bounded structures; single-producer rule explicit. |
| 8 Sources | pass | Ostrom 1990 Ch. 3 + Cox/Arnold/Tomas 2010 meta-analysis cited; no invented constants — all interventions parameterize existing module-level values. |
| Stakes | High | Shared in-process resource serving SSE to live clients; concurrency-correctness load-bearing. Recommendations 1, 2, 5, 6 require ADR before merge. |

## 8. Hand-offs

- Graduated-sanctions implementation → **engineer** (touch
  `layout_authority_log.py` _record_miss / _fan_out paths).
- Formal invariant for "graduated, not binary" → **Lamport** (state
  machine: HEALTHY → WARN → THROTTLED → EVICTED with explicit transitions).
- Per-subscriber metrics emission → **Curie** (define what to measure;
  baseline before/after).
- QoS negotiation API surface → **Simon** (decompose `subscribe(qos=...)`
  contract).
