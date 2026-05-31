# Pólya — Heuristic Audit of the Layout Authority Stuckness

> "If you cannot solve the proposed problem, look around for an
> appropriate related problem." — *How to Solve It*, 1945.

Ten fix cycles with no convergence is the canonical signature of a
problem attacked at the wrong level of generality. Pólya's
prescription is not "push harder"; it is **change the framing**.

## 1. Phase 1 — Understand. Restated.

- **Unknown:** a coordinator that places streamed nodes/edges at
  deterministic (x, y) and emits them to the renderer.
- **Given:** six modules (`geometry`, `protocol`, `scheduler`,
  `log`, `wire`, `lod`), each internally consistent; cost model;
  ~20 sibling audits.
- **What is missing:** the integrating module
  `layout_authority.py`. Feynman §1 step 2: *"every chain of
  reasoning below is what would happen if it were written. Today
  nothing calls `add_node` at all."*

The user's restatement has been "fix the layout authority." The
true restatement: **the parts exist, the assembly does not, and
each fix has touched a part instead of the assembly.** The bug is
not in any file; the bug is in the *absence* of one.

## 2. Have you seen this problem before? — Related solved problems

### 2.1 IoT sensor streaming charts (the user's analogy)

Same structural problem: unbounded events arrive out of order;
each must land at deterministic screen position; backend cannot
replay history per client. The IoT recipe maps 1:1:

| IoT piece | Cortex equivalent | Status |
|---|---|---|
| Sensor → broker (MQTT QoS) | `add_node` → `scheduler.submit` | exists |
| Broker → time-series store (ring) | `log.emit` (500k ring) | exists |
| Pure projection `(id, t) → (x, y)` | `compute_slot(...)` | exists |
| **Coordinator** owning counters + routing | `layout_authority.py` | **MISSING** |

Every IoT system has one coordinator object. We have six modules
(broker, store, projection) and no coordinator. **Adapted method:
copy the IoT coordinator pattern verbatim — one class, one worker
thread, one counter map, two buffers.** ~150 LOC. Dijkstra D0–D2
and Feynman §4 already enumerated its obligations.

### 2.2 Database WAL + replicas

`log.py` is a WAL. Subscribers are replicas reading by seq.
`request_subtree` is checkpoint+replay. The Postgres
streaming-replication ordering proof (single producer → seq
monotonic → per-replica order) is identical and two lines.
**Borrow the WAL ordering argument; no new invariant needed.**

### 2.3 matplotlib `FuncAnimation`

Counter on the figure, projection as closure, emit as
`canvas.draw`. Cortex authority is the same shape distributed
across threads. **Borrowing the mental model collapses I3/I4/I7
into "the counter map is the state; everything else is a pure
function of it."**

## 3. Can you solve a simpler version? — One-domain authority

Specialize hard:

> **Special case: ONE domain, ONE kind (file), no edges, no
> re-emit, in-memory dict, single thread.**

```python
class TinyAuthority:
    def __init__(self, anchor):
        self.anchor = anchor
        self.counter = 0
        self.slots = {}

    def add_node(self, node_id):
        idx = self.counter
        self.counter += 1
        x, y = compute_slot_file(self.anchor, idx,
                                 total=max(self.counter, 1))
        self.slots[node_id] = (x, y)
        return (idx, x, y)
```

Three things fall out:

1. **`total` is a moving target** — file #1 is placed against
   `total=1`; later geometry expects `total=10`. The "no
   retroactive reseat" decision (I4/I7) is load-bearing; the
   simpler version makes it concrete.
2. **The counter map belongs in the coordinator,** not in
   geometry/scheduler/log (Feynman §1.5c spent four bullets
   searching for whose job it is).
3. **Edges and re-emit are additions on top,** not intrinsic —
   buffers + replays on the counter+projection core. Build last.

## 4. Work backward from the desired result

Forward attempts are stuck. Reverse direction. Terminal state:

> Browser shows nodes appearing at deterministic positions as the
> build worker streams events.

Walk backward:

1. Browser shows node ⇐ SSE delivers `slot` event with finite floats.
2. SSE delivers ⇐ `log.emit('slot', bytes)` was called.
3. `format_slot` produced bytes ⇐ it read the right field name.
   **Today it reads `slot.id`; protocol exposes `node_id`.
   AttributeError on first call.** (Feynman §1.8; Dijkstra D0.)
   **5 LOC, 1 test. Blocks every downstream piece.**
4. `format_slot` was called ⇐ a worker thread popped the
   scheduler. **Worker does not exist.**
5. Worker computed geometry ⇐ counter map and pending-edges
   buffer exist. **Both missing; both belong in the coordinator.**
6. `add_node` was called ⇐ coordinator object exists. **Factory
   at `protocol.py:222` imports a module not in the tree.**

**Strict critical path, in order:**
1. Fix `wire.format_slot` field name.
2. Write `layout_authority.py` coordinator (~150 LOC).
3. Wire factory; unblock `protocol.py:229`.
4. Connect build worker to the coordinator.

**Ten fix cycles touched these at random. Backward walk gives the
order.**

## 5. Phase 2 — Plan: heuristic and why

**Selected: specialize-then-generalize, executed under the
IoT-coordinator pattern, on the backward-walk's critical path.**

IoT analogy gives shape; backward-walk gives order; simpler-
version controls scope. Composed, they keep the six modules
intact (they already *correctly* are broker/store/projection/
protocol/encoder/LoD) and add the missing coordinator on top in
the right order.

## 6. Plan — next moves, in order

| # | Move | Cost | Unblocks |
|---|---|---|---|
| 1 | Fix `wire.format_slot` (`slot.id` → `slot.node_id`); round-trip test with real `SlotAssignment`. | ~10 min | every downstream test |
| 2 | Write `TinyAuthority` (1 domain, 1 kind, no edges, no re-emit). E2E test: 1000 `add_node` → 1000 SSE events → 1000 (x, y) decoded. | ~2 h | IoT pattern proven in-tree |
| 3 | Generalize to 11 domains × 6 kinds via counter map keyed `(dom, kind)`. Reuse worker loop. | ~2 h | Feynman §1.5c resolved |
| 4 | Parent-pending buffer (I3, 32k cap, drop+counter). | ~1 h | symbols-before-files no longer races |
| 5 | Pending-edges buffer (I5, 100k cap). | ~1 h | edges no longer dangle |
| 6 | `request_subtree` re-emit walking counter map. | ~1 h | I2 closes |
| 7 | Wire build worker → coordinator. Demo on real repo scan. | ~1 h | user sees nodes appear |
| 8 | Curie: RSS, drop rates, p99 at 10⁶/sec. | ~1 d | Dijkstra B1–B6 empirically |

Total: ~2 days. **Less than the last 10 fix cycles cost.**

## 7. Phase 4 — Look back. Reusable lessons.

- **Stuckness signal:** when a fix lands and the next bug is one
  layer away, the problem is not in the layer you are touching.
  Stop and look for the missing assembly module. Second
  occurrence in this codebase (cf. early `consolidation_engine`
  / dual-store CLS wiring).
- **Rule:** before fixing module N, verify it is *called* by
  something. Zero callers ⇒ write the integrator before any
  further fix.
- **Rule:** a 6-module subsystem with 20 audits and no E2E test
  needs a coordinator, not another audit. Treat absence of an
  E2E test as a red flag equal to a failing test.
- **Domain transfer:** "broker + store + projection +
  coordinator" is the right shape for any high-rate,
  deterministic-placement, single-producer streaming problem.
  Add to the architecture playbook.

## 8. Hand-offs

- **engineer:** items 1–7; start with item 1 (10-min unblock).
- **Dijkstra:** review `TinyAuthority` for single-producer +
  seq-monotonic before generalizing.
- **Curie:** item 8 after item 7. **Hamilton:** SSE backpressure
  (cost-model §7) once item 7 lands.
