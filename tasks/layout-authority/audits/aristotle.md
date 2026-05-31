# Aristotle Audit — Layout Authority Four Causes

Frame: for each of the five `layout_authority_*` modules, name what it is
made of (material), what shape it takes (formal), what brings it into
being (efficient), and what it exists to solve (final). Then synthesize
across modules to find causes that are incomplete or that disagree.

Sources: `_protocol.py`, `_log.py`, `_scheduler.py`, `_geometry.py`,
`_lod.py`, `_wire.py`; `cost-model.md`; audits `alexander.md`, `beer.md`,
`dijkstra.md`.

## Per-module four causes

### `layout_authority_protocol.py`

- **MATERIAL.** `frozenset[str]` of NODE_KINDS / EDGE_KINDS;
  `@dataclass(frozen, slots)` value types `NodeDelta`, `EdgeDelta`,
  `SlotAssignment`; a `runtime_checkable` `Protocol`; a doc-string
  `INVARIANTS` block (I1–I7); stdlib-only imports (`dataclasses`,
  `typing`).
- **FORMAL.** A *contract module* — three input verbs (add_node,
  add_edge, request_subtree), one output event (SlotAssignment), one
  Protocol. Shape is normative-spec, not behavior; pure typing.
- **EFFICIENT.** Authored as the contract layer that downstream impls
  (`layout_authority.py`) and adapters (`_wire`, `_log`) must honor.
  Forward-declared factory `authority_from_geometry` defers to a
  reference impl that is **not present in the audited set** (gap).
- **FINAL.** Make happens-before, ordering, and per-kind preconditions
  *enforceable by reading one file*. Lets engineer + Dijkstra argue I1–I7
  without spelunking. Final cause = "shared meaning across producer,
  authority, and consumer."

### `layout_authority_log.py`

- **MATERIAL.** `collections.deque(maxlen=500_000)` of `(seq, kind,
  bytes)` tuples; two `threading.Lock`s; `list[queue.Queue]`
  subscribers, each `maxsize=100_000`; module-globals
  (`_event_log`, `_event_seq`, `_subscribers`).
- **FORMAL.** Append-only ring buffer + snapshot fan-out with
  per-subscriber dead-queue reaping at 200 misses; replay-by-seq with
  gap detection; `reset()` clears buffer but **preserves** monotonic
  seq across builds.
- **EFFICIENT.** Driven by `emit(kind, payload)` from a single producer
  thread (the worker that pops `_scheduler` and renders frames via
  `_wire`). Subscribers are added by SSE handlers from any thread.
- **FINAL.** Deliver every wire-encoded event to every live SSE
  subscriber exactly once and in seq order, support `Last-Event-ID`
  resume across reconnects, and never stall the producer when a
  subscriber is slow. Final cause = "one-to-many durable replay."

### `layout_authority_scheduler.py`

- **MATERIAL.** Seven `collections.deque` queues with hand-derived caps
  (P0=1k…P5=128k, P6=100); a `threading.Lock` + `Condition`; a `Stats`
  dataclass of `queued`/`dropped` counters per priority.
- **FORMAL.** Hamilton 1202-pattern bounded multi-queue with strict
  priority pop, non-blocking `submit` returning False on cap, and
  idempotent P6 coalescing by linear scan. Drops accounted, never
  silent.
- **EFFICIENT.** `submit` called from build-worker thread per
  add_node/add_edge; `pop` called from the single authority worker
  loop; `coalesce_subtree` from any thread (HTTP handler).
- **FINAL.** Survive bursty unbounded producer load while keeping
  topologically critical hubs (P0 domains, P1 tool_hubs) intact and
  shedding cheap volume (P4 symbols, P5 edges) first. Final cause =
  "graceful priority-displaced shedding."

### `layout_authority_geometry.py`

- **MATERIAL.** Module-level `float` constants ported verbatim from
  `ui/unified/js/workflow_graph.js` (radii, sector half-widths,
  per-tool angles, golden angle φ); pure-`math` arithmetic.
- **FORMAL.** Eight closed-form O(1) placement helpers + a `compute_slot`
  dispatcher keyed on `node_kind`. Pure functions; no state, no
  iteration over siblings. Memory: O(domains × kinds) ≈ 528 B.
- **EFFICIENT.** Called once per accepted NodeDelta by the authority
  worker, given a `ctx` dict (anchor, outward, idx, total, …). Was
  produced by mechanically translating `workflow_graph.js` lines
  43–700 into Python.
- **FINAL.** Place node #10⁹ in the same time as node #1; match the
  user-tuned visual contract. Final cause = "deterministic, stable,
  visually-faithful pixel coordinates at constant cost."

### `layout_authority_lod.py`

- **MATERIAL.** Three `frozenset[str]` of kinds (always-visible,
  decimated, far-reduced); a `_FAR_ZOOM_THRESHOLD = 0.4`; BLAKE2b
  digest as the stable hash; a power-law `stride(zoom)` formula.
- **FORMAL.** Pure-function decimator: `visible_at_zoom(node_id, kind,
  zoom)` returns bool. Streaming `visible_subset` iterator. Power-law
  signature `|visible| ≈ N / stride(zoom)`, log-log slope ≈ −1
  (Mandelbrot self-check).
- **EFFICIENT.** Invoked by the SSE handler at (re)connect when
  client passes `?zoom=`; produces the surviving subset to stream.
- **FINAL.** Make a 10⁶+ symbol population renderable at far zoom
  without overwhelming the canvas, and have *the same* visible set
  survive disconnect/reconnect. Final cause = "scale-invariant
  visibility that is reconnection-stable."

### `layout_authority_wire.py`

- **MATERIAL.** Pre-allocated `bytes` constants (`_EVT_SLOT`,
  `_DATA_PREFIX`, `_NL`, `_PIPE`, …); pure-stdlib `math.isfinite`;
  ASCII-byte concatenation; pipe-delimited UTF-8.
- **FORMAL.** A real-time codec returning finished `bytes` per event
  (`format_slot`, `format_edge`, `format_done`, `format_keepalive`,
  `chunk_wrap`); paired test-only decoders. Validates against `|`,
  `\n`, `\r`, NaN, inf, oversize kind. ~82 B/event wire shape.
- **EFFICIENT.** Called by the authority worker between `compute_slot`
  and `_log.emit`; finished bytes flow into the ring buffer and out
  to every subscriber unchanged.
- **FINAL.** Encode-once, fan-out-many at ~1 M events/s; let the
  browser parse with `String.split('|')` (~4× cheaper than
  `JSON.parse`). Final cause = "minimum bits per event on the wire,
  zero re-encoding per subscriber."

## Synthesis — gaps where causes are incomplete or disagree

1. **Material/formal mismatch (D0 from Dijkstra audit).**
   `_protocol.SlotAssignment.node_id` vs. `_wire.format_slot` reading
   `slot.id`. The matter (field name) contradicts the form (the
   protocol contract). Aristotelian rule: matter must take the form
   the contract specifies. **Block integration until renamed.**

2. **Efficient cause for the whole authority is unverified.** Every
   module names "the authority worker" as its efficient cause, but
   the consolidating `layout_authority.py` (the worker loop, the
   parent-pending buffer, the single-producer `emit` discipline) is
   **not in the audited set**. Until that file is read and shown to
   wire scheduler→geometry→wire→log under one thread, the chain of
   efficient causes has a missing link. Dijkstra D1/D2 and Beer's
   "S3 broker absent" both name this same gap.

3. **Final cause coherent across modules.** Place 10⁹ nodes in 1–2 s,
   8 MB working set, deterministic stable slots, reconnection-stable
   visibility, lossless replay. Every module's *for-the-sake-of*
   composes into the same higher-level purpose. No teleological
   conflict.

4. **Formal cause of `_log` violates one of its own invariants.**
   The reset prose says seq is global-monotonic across builds;
   the module-global state means *two authorities in one process
   share seq*. The form (single global counter) does not match the
   intended substance (per-authority resume semantics). Either a
   construction precondition ("one authority per process") must be
   asserted, or `_log` must be refactored to instance state. This
   is the same defect Dijkstra calls D2 and Beer calls "fragile
   cohesion of `_log`."

5. **Material cause of `_scheduler` exceeds the cost-model budget.**
   `cost-model.md` declares an 8 MB ceiling; `_scheduler` worst-case
   residency is ~19.4 MB (sum of caps × ~80 B). The matter from
   which the scheduler is built cannot in principle fit the form
   imposed by the cost model under simultaneous burst. Either P5
   cap shrinks, the ceiling is renegotiated in an ADR, or the
   measured steady-state must be empirically shown <8 MB.

6. **Algedonic gap (Beer) = absent final cause for failure surfacing.**
   No module has "tell the operator we are degraded" as its final
   cause. `replay_lost` is the only true push signal; queue overflow,
   subscriber-reap, and invariant violation are pull-only. The system
   has no module *for* alarm. A genuine S3 broker is missing both as
   matter (no module) and as final cause (no purpose claimed for it).

## Hand-offs

- D0 field-name fix and single-producer enforcement → **engineer** (per
  Dijkstra).
- S3 broker design (final-cause "surface degradation"), runtime
  invariant enforcer → **Hamilton + engineer** (per Beer).
- Memory-budget reconciliation between scheduler caps and cost-model
  8 MB ceiling → **Curie** (measure) + **engineer** (decide).
- Read and audit the unread `layout_authority.py` worker file to close
  the efficient-cause chain → **engineer + Dijkstra**.

## Verdict

Material, formal, and final causes are well-articulated and largely
coherent across the five audited modules. The **efficient cause is
incomplete**: the orchestrating worker is referenced in every module's
threading model but is not part of the audited set. Two specific
material-form mismatches (D0 field name, `_log` global state) and one
material-form-vs-cost-model contradiction (scheduler 19.4 MB > 8 MB)
must be resolved before the four causes converge.
