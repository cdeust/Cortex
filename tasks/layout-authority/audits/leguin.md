# Le Guin — Speculative-Architecture Audit of the Layout Authority

> *The Dispossessed* presents Anarres as an **ambiguous utopia**: every
> architectural choice has costs, and the honest design names them.
> Three alternatives to "one authority, one log, one stream" are
> rendered below — not to choose, but to make the present design's
> costs visible by contrast. Method: *single-variable thought
> experiment* (Le Guin 1969) — change one assumption, trace
> consequences through every layer, name the irreducible trade-off,
> and identify the regime in which the alternative is the right choice.

**Reference.** Single `LayoutAuthority`, global monotonic `_event_seq`,
one SSE stream per client, one Postgres `layout_version` per recompute.
Costs audited in `borges.md`, `ostrom.md`, `coase.md`.

---

## (a) FEDERATED — N authorities, one per domain

**Variable changed.** `LayoutAuthority` becomes `{domain_id → LayoutAuthority}`.
Each owns its slot counters, event log, subscribers, `_event_seq`.
Client opens N SSE streams; merge happens browser-side.

**Trade-off vs current.**

| Dimension | Unitary | Federated |
|---|---|---|
| Cross-domain causal order | Globally monotonic | **Lost** — vector clock, partial order only |
| Concurrent recomputes (Borges §1.2) | Corrupts | Eliminated (domain-isolated) |
| Event-log capacity | 500k shared | 500k × N — scales with domains |
| Wire cost per client | 1 SSE | N SSE (HTTP/2 stream overhead) |
| Subscriber-eviction blast radius | All events lost | One domain only |
| Fibonacci anchor allocation | Owned by single authority | **No home** — needs shared registry |
| Cross-domain edges | First-class | **Stateless** — belong to neither authority |

**Irreducible cost.** *Federation buys isolation by paying with
coherence.* The client must reason in vector clocks (Lamport 1978):
O(N) to compare, O(N) to ship, partial-order only. Cross-domain edges
have no home — Borges §1.7's pending-edges weakness becomes
**structural**, not contingent.

**Live-with-it test (year 3).** New domain added — where do its
Fibonacci anchors come from? Some authority must allocate them, or
they collide. Federation is never *flat*; it gravitates to "N+1
services" or "shared config silently centralised." The name stops
being accurate within months.

**When federation is right.**
- **Multi-tenant SaaS:** isolation is a product requirement;
  cross-tenant ordering is meaningless; anchors are tenant-local.
- **Geo-distributed editors:** each region pays the vector-clock cost
  for sub-50ms write latency.
- **Domains × event rate exceeds one-process budget** (~10⁵ evt/s on
  the global `_event_seq` lock).

---

## (b) CRDT — distributed authorities, eventual consistency

**Variable changed.** No canonical authority. Every writer (build
worker, browser, replay agent) holds a local replica. Slots are LWW
registers keyed on `node_id` with Lamport-stamp tiebreak; edges are
OR-Sets. Replicas gossip; convergence is eventual.

**Trade-off vs current.**

| Dimension | Unitary | CRDT |
|---|---|---|
| Source of truth | Authority's slot table | **None** — convergence |
| Determinism (same input → same coords) | Yes | **No** — coord flickers until convergence |
| Offline writes | Impossible | Possible |
| `topology_fingerprint` | Coverage proof | **Undefined** — no "the" topology |
| Wire cost per op | ~80 B | ~120 B (op + Lamport stamp + replica id) |
| Garbage collection | `TRUNCATE` | **Hard** — tombstones must outlive partition window |

**Irreducible cost.** *CRDT buys availability by paying with
geometric purity.* `cost-model.md §3` proves the geometry is closed
form on `(domain_anchor, kind, idx, total_in_kind)`. **CRDT breaks
`total_in_kind`.** Replica A places file #4 at θ₄ from its observed
count of 3; replica B observes 5 and places at θ₄′. Convergence picks
one — the loser's coordinate **was real, was rendered, and now
teleports**. The user sees nodes jump. This is irreducible: ordering
the integer indices commutatively requires Logoot/Treedoc IDs whose
periodic rebalance *is* the moment the coordinates shift. There is
no version of this story where a node never moves.

**Live-with-it test (year 5).** Tombstones never truly leave — some
replica might still be offline. Tombstone table grows monotonically.
Team adds "GC tombstones >30 days"; a laptop offline for 31 days
reconnects and resurrects 500 deleted nodes. Team adds "max offline
window" — system is no longer offline-tolerant, which was the entire
point. *Le Guin's Anarres: freedom from authority creates a subtler
authority — the tyranny of the gossip clock.*

**When CRDT is right.**
- **Collaborative manual placement** (Figma multiplayer): position is
  *opinion*, not *function*; LWW is a feature.
- **Long-running offline writers** (rare in server-side pipelines).
- **Disaster recovery** is the dominant non-functional requirement
  and a fuzzy view beats no view. (Cortex's stakes do not warrant
  this.)

---

## (c) PUSH-PULL — authority emits diffs, clients pull on viewport changes

**Variable changed.** SSE stream becomes a thin position ticker —
`(seq, node_id, kind, x, y)` only. No edges, no metadata, no
membership. Edges and node detail are PULLED on viewport change via
`GET /api/nodes?ids=…&fields=…`.

**Trade-off vs current.**

| Dimension | Unitary | Push-Pull |
|---|---|---|
| Wire bytes per event | ~80 B (slot) + ~60 B (edge) | ~24 B (slot only) |
| Server CPU for off-screen clients | Same as on-screen | **Order of magnitude lower** |
| Round-trip on viewport pan | 0 (already streaming) | 1 RTT per pan |
| Edge orphans (Borges §1.7) | Pending-edges buffer | **Eliminated** — fetched against snapshot |
| Freshness model | One clock (`seq`) | **Two clocks** — `seq` + ETag |

**Irreducible cost.** *Push-pull buys bandwidth by paying with
interactivity.* Today, panning is instant: every record is in the
browser. After push-pull, panning to 10k uncached nodes fires a 10k-id
batch fetch; the user waits. Engelbart's principle: cost of
interaction must not exceed cost of thought. Two clocks (position
seq vs metadata ETag) admit observable inconsistencies — node moves
to new slot before its tooltip name updates. Reconciliation logic has
its own bugs that depend on network race ordering.

**Live-with-it test (year 1).** First 10⁶-node graph: diagonal pan
across sparse-then-dense region triggers prefetch avalanche. Team
adds bounding-box prefetch heuristic, then velocity predictor, then
loading spinner. Spinner becomes permanent UI. The original story
("everything streams, everything is current") is gone, replaced by a
four-layer cache stack the next engineer must learn to debug a stale
tooltip.

**When push-pull is right.**
- **N ≫ visible** (10⁹ nodes, 10⁴ in viewport): the unitary design
  cannot survive `cost-model.md §1`'s 1ns/node ceiling under full
  metadata streaming. Push-pull is mandatory at this scale.
- **Bandwidth-asymmetric clients** (mobile, throttled tabs).
- **Read-heavy, edit-rare** (99% viewers): unitary edge fan-out is
  wasted CPU.
- **The PULL backend already exists** — Cortex's `recall_memories`
  *is* the metadata fetcher. Half of push-pull is implemented.

---

## Irreducible trade-offs (table)

| Architecture | Gain | Loss | Bearer of cost |
|---|---|---|---|
| **Unitary** (current) | Determinism, single replay clock, simple mental model | Single-process scaling ceiling, concurrent-recompute corruption | Team, when N × evt-rate exceeds one-process budget |
| **Federated** | Isolation, per-domain scaling, fault containment | Global causal order, cross-domain edges, simple mental model | Client (merge); on-call engineer (N event logs) |
| **CRDT** | Availability, offline writes, no SPOF | Determinism, geometric purity, simple GC | **End user — every node teleport during convergence** |
| **Push-Pull** | Bandwidth, per-viewer scaling, fits 10⁹ nodes | Pan latency, single-clock simplicity, cache-free reasoning | End user (pan wait); next engineer (two-clock races) |

## Container-narrative reframe (Le Guin 1986)

Each design tells a *story* hiding one cost while revealing another:
- **Unitary:** "one authority is truth." Hides SPOF + contention.
- **Federated:** "truth is local." Hides cross-domain reality.
- **CRDT:** "truth is convergent." Hides UX cost of divergence.
- **Push-Pull:** "truth is fetched on demand." Hides demand latency.

No story without a hidden cost. The honest design names the cost it
chose. Alternatives are not *better* — they are *differently costly*.
Pick the cost you can live with for five years.

## Hand-offs

- Vector-clock & convergence formalism → **Lamport**
- Cross-domain edge supervisor design → **Erlang**
- Two-clock cache reconciliation under causal DAG → **Pearl**
- Empirical viewport-pan latency budget → **Curie**
- Tenant/anchor-registry economic design → **Coase**
- UI tolerance for node-teleport / loading-state → **Bruner**
