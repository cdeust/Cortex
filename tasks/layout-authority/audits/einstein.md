# Einstein gedankenexperiment — riding one event through the layout authority

**Method.** I am a single `add_node` event traveling through the pipeline.
At each frame I record: what is conserved, what changes form, what the
local observer believes, what could go wrong.

**The event I am.** `add_node(NodeDelta(node_id='symbol:abc',
kind='symbol', domain_id='domain:cortex', parent_id='file:xyz'))`.
Conserved across every frame: `node_id`. Everything else transforms.

## Frame 1 — Build worker thread

**Form.** Frozen Python dataclass, ~80 B, five named fields. Typed.
**Observer.** Sees full semantics; `kind='symbol'` implies `parent_id`
mandatory (precondition in `NodeDelta` docstring).
**Risk.** Field-name divergence with the wire layer
(`SlotAssignment.node_id` vs `format_slot` reading `slot.id`,
wire.py:103) is invisible from here. Feynman §1.8 flagged it.

## Frame 2 — `authority.add_node`

**Form change.** Dataclass → "intent to enqueue".
`priority_for_node('symbol')` → `PRIORITY_SYMBOL = 4`
(scheduler.py:106). Then `submit(4, self)`.
**Observer.** Sees only my `kind`. `domain_id`, `parent_id`,
`tool_name` are opaque payload at this layer.
**Risk.** P4 cap is 64,000 (scheduler.py:83). Full → `submit` returns
`False`, `_stats.dropped[4] += 1`, no exception, no log. Silent drop
unless the integrator inspects the bool — and **the integrator
(`layout_authority.py`) does not exist yet** (Feynman §4).

## Frame 3 — In the P4 deque

**Form.** A reference inside `collections.deque` under
`threading.Lock`. Cross-thread.
**Observer.** Pure FIFO position. P0–P3 must drain first. Hamilton
"1202" guarantee: high priority always wins (scheduler.py:8–13).
**Risk.** Indefinite starvation under sustained P0–P3 load. The
scheduler does not promise liveness for low priorities; this is a
documented feature.

## Frame 4 — Authority pop + context assembly

**Form.** Back to `NodeDelta` in worker thread.
**Observer.** For `kind='symbol'`, `compute_slot` needs `file_slot`,
`idx`, `total` (geometry.py:170–179). The integrator must look up
`file_slot` for `parent_id='file:xyz'` from a "main store"
(scheduler.py:154 references it; not yet coded).

**Risk — the I3 case.** If `file:xyz` has not yet been processed,
its slot does not exist. Per protocol I3 (protocol.py:194), I am
buffered. **That buffer does not exist as code in the six audited
modules** — only in prose. Same for I5 (pending edges). The
integrator owns it. Naive integrator → I sit forever.

**Equivalence-principle observation.** From the consumer's vantage,
*"buffered symbol"* and *"dropped symbol"* are empirically
indistinguishable: both produce no slot event for me. The producer
distinguishes them via `dropped[4]` counter. **This is a covariance
gap between producer-belief and consumer-observation.** Either emit
a `pending` event or document the frame dependence.

## Frame 5 — `slot_for_symbol`

Assume parent landed and I am replayed.
**Form change.** Three values: `(file_slot, idx_in_file, total_in_file)`.
**Math.** angle = 2π·(idx+0.5)/total; r = 18 + (idx%4)·3;
return `(file_slot.x + r·cos(angle), file_slot.y + r·sin(angle))`
(geometry.py:170–179). O(1), pure, stateless.
**Observer.** *Sees only floats.* `node_id` is invisible here.
Identity is held outside this frame by the integrator's bookkeeping.
**Risk — silent NaN.** If `file_slot` contains NaN (because the
file landed before its tool_hub and got a placeholder anchor — I4
edge case), my `(x, y)` inherits NaN and is rejected at the wire
layer three frames later. **No frame in the geometry chain checks
finiteness.** The math is "covariant under finiteness" only if every
input is finite; geometry trusts its caller.

## Frame 6 — `SlotAssignment` + `format_slot`

**Form.** `SlotAssignment(seq, node_id, x, y, kind, domain_id)`
(protocol.py:103–129) → bytes.
**The hard bug.** `wire.format_slot` reads `slot.id` (wire.py:103);
the dataclass field is `node_id`. **`AttributeError`** here in
current code. The wire benchmark hides it with a local `_Slot` whose
field is `id` (wire.py:209). One-side rename fixes it.
**If fixed.** Bytes:
`b"id: 42\nevent: slot\ndata: symbol:abc|123.4|567.8|symbol|domain:cortex\n\n"`.
**Conserved.** `node_id` is the first pipe-field. `seq` is added —
Lamport-style logical timestamp; *not* identity.
**Form change.** Type system erased. UTF-8 bytes. Five fields by
string position, recovered by `.split('|')`.
**Risk.** A `node_id` containing `|` or `\n` collapses framing.
`_validate_id` (wire.py:64) catches at emit; protocol layer rejects
earlier. Two defenses for one invariant — fine.

## Frame 7 — Event log + fan-out

**Form.** Tuple `(seq, 'slot', bytes)` in 500k-cap deque (log.py:42).
`put_nowait` to every subscriber (cap 100k each, log.py:43).
**Observer.** Log sees opaque bytes. Routing by kind string only.
Strict per-instance seq monotonicity (log.py:217–223).
**Risk.** Slow subscriber: `put_nowait` raises Full, miss counter
increments, after 200 consecutive misses the subscriber is reaped.
A reader's view diverges permanently from the log's view. Fall-out
of 500k buffer → `replay_since(N)` returns `oldest > N+1` and the
client falls back to a snapshot. Lamport "causal cut" by design.

## Frame 8 — SSE handler → socket

**Form.** `chunk_wrap` wraps payload in HTTP/1.1 chunked framing
(`<hex-len>\r\n<bytes>\r\n`, wire.py:162). Bytes go to TCP.
**Observer.** Wire layer sees length-prefix only. Kernel sees TCP.
Identity invisible at this layer; `node_id` survives only as a
substring of opaque bytes.
**Risk.** Connection drop → reconnect with `Last-Event-ID`. If my
seq is still in the ring buffer, I am replayed; if not, snapshot
fallback re-derives me from the build cache (outside this audit).

## Frame 9 — Browser `EventSource.onmessage`

**Form.** `MessageEvent` with `.data =
"symbol:abc|123.4|567.8|symbol|domain:cortex"` and `.lastEventId =
"42"`. JS does `event.data.split('|')`.
**Important fact.** Grep across `ui/` shows **no `EventSource`
consumer wired today**. The frontend currently fetches
`/api/quadtree` (Apache Arrow IPC, gzipped) — snapshot, not stream
(workflow_graph_tilemap.js:53). Frames 9–10 describe the wired
future state. Today my event dies at Frame 7 (in the log; no
visualization subscriber drains it).
**Risk (when wired).** If the consumer keys by `node_id` and
overwrites unconditionally, behavior matches the contract in the
happy path but diverges under out-of-order delivery (proxies, WAN
reorder). Contract I2 says: **update by seq, higher wins**.
*The contract is observer-frame-dependent unless consumers respect
seq.* Two valid implementations are not empirically equivalent under
`request_subtree`-driven reseat.

## Frame 10 — Canvas paint

**Form.** `(x, y)` mapped from authority coords (1000×1000 default,
geometry.py header) to viewport pixels. Color from
`KIND_COLOR['symbol'] = [100, 116, 139, 230]`
(workflow_graph_tilemap.js:31). `node_id` lives in a parallel
array; flatbush spatial index resolves clicks back to id.
**Observer.** A grey-blue dot near the file's cyan dot. The user
recovers `node_id` only on hover/click.
**Conserved.** Spatial coincidence with parent file — geometry
guarantees this by construction.
**Risk.** If the file reseated via `request_subtree` after my
geometry was computed (Frame 5), I am drawn at the *old* file
position. I3 says symbols never reseat retroactively. I float,
orphaned. **Observable covariance violation:** my position is meant
to be a function of parent position, but the function evaluation
is frozen at my creation time.

---

## Operational definitions surfaced

1. **"a node arrived."** Wire emitted a `slot` event with this id and
   log assigned a seq. **Not** "build worker called `add_node`" —
   that may have been silently dropped at P4 cap.
2. **"a node was dropped."** Producer `submit` returned `False` AND
   no later `request_subtree` reseated it. **Indistinguishable from
   "buffered awaiting parent" to a pure-stream consumer.**
3. **"a node is at (x, y)."** Most recent `SlotAssignment` for that
   id (highest `seq`) places it there. Older `(x, y)` for the same
   id are superseded. **Holds only if consumers update by seq.**

## Equivalence audit

| Pair | Distinguishable? | Verdict |
|---|---|---|
| Buffered vs dropped (consumer-only view) | No (until parent arrives) | Same observable; producer counters disagree → covariance gap |
| Out-of-order vs in-order slot for same id, seq-keyed consumer | No | Same |
| Out-of-order vs in-order, id-keyed consumer | Yes (different final (x,y) under reseat) | Different — protocol must mandate seq-keyed |
| "No JS consumer wired" vs "all events delivered nowhere" | No (from producer side) | Same — current state of the system |

## Hand-offs

- **Reseat invariance ↔ conserved quantity** → Noether.
- **Quantity of dropped vs buffered events on the wire** → Shannon
  (separate stats stream so consumers can reconstruct producer
  belief).
- **End-to-end latency `add_node` → canvas paint** → Curie. Today
  the chain is broken at Frame 4 (no integrator) and Frame 9 (no
  EventSource consumer); measurement is meaningful only after both
  exist.
- **Field-name bug `slot.id` vs `slot.node_id`** → engineer (trivial;
  Feynman flagged independently — convergent finding).
