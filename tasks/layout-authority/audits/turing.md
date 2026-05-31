# Turing Reduction — Layout Authority

**Frame:** strip every module to the simplest abstract machine that streams `(id, x, y)` from build worker to SSE consumer. What is load-bearing? What is accidental complexity?

## 1. Problem

```
Problem: stream (node_id, x, y, kind, domain_id) and (src, tgt, kind) deltas
         from a single producer (build worker) to N HTTP/SSE consumers,
         with monotonic seq for Last-Event-ID resume.
```

## 2. Simplest machine

| Class | Verdict |
|---|---|
| Finite automaton | No — unbounded sequence numbers, unbounded node set. |
| **Pushdown automaton (single-stack ordering)** | **Sufficient.** The only structural state is "has parent X been emitted yet?" → a buffer of pending children. |
| Turing machine | Overkill. No tape rewrite needed; events are append-only. |

The problem reduces to: **a pure function `kind × bucket_idx × domain_anchor → (x,y)`, behind an append-only log, behind an SSE encoder, with one buffer for I3 (symbol-after-file) and one for I5 (edge-after-endpoints).**

Decidability: trivially decidable — every operation is O(1) closed-form arithmetic. Complexity: O(1) amortized per event, O(N) total. No optimization question exists; the Turing question is the structural one — what's necessary?

## 3. Reduction by module — load-bearing vs accidental

Current: ~2,196 lines across 10 files. Reduced essence:

| Module | Lines | Load-bearing | Accidental | Min lines |
|---|---|---|---|---|
| `layout_authority_geometry.py` | 218 | All 9 placement formulas + dispatcher. Every constant cites `workflow_graph.js`. | Self-check `_benchmark` only used in `__main__`. | **~150** |
| `layout_authority_protocol.py` | 230 | 3 dataclasses (NodeDelta, EdgeDelta, SlotAssignment). | `Protocol` ABC, `INVARIANTS` docstring constant, `authority_from_geometry` factory stub, NODE_KINDS/EDGE_KINDS frozensets (str literal check suffices). | **~40** |
| `layout_authority_log.py` | 230 | `emit() → seq`, `subscribe()/unsubscribe()`, `replay_since()`. | Dead-queue miss counting + reaping (200-miss threshold), 500k ring buffer cap (a 10k cap suffices for Last-Event-ID resume window), `stats()`, `_record_miss/_clear_misses` attribute-injection trick. | **~50** |
| `layout_authority_wire.py` | 241 | `format_slot/edge/done` byte builders. Pipe-separated payload. | `chunk_wrap`, `format_keepalive`, `format_terminator` (the SSE handler does this), `parse_slot/parse_edge` (test-only), `_benchmark`, defensive `_validate_id/_validate_kind/_validate_finite` (already validated upstream). | **~40** |
| `layout_authority_scheduler.py` | 264 | **Nothing in the streaming hot path.** | Entire module. The reference `LayoutAuthority.add_node` is synchronous + non-blocking + O(1); priority shedding is dead theatre. P0–P6, Hamilton 1202 reference, `coalesce_subtree`, `is_overloaded`, the per-priority deques — none of it is wired to the actual emission path; emission happens inline in `add_node`. | **0 (cut entirely)** |
| `layout_authority_lod.py` | 193 | Zero in the streaming path. | Entire module. The build worker never consults `visible_at_zoom`; the SSE handler can decimate symbols downstream with `hash(id) % stride` in 5 lines if/when needed. | **0 (cut entirely)** |
| `layout_authority.py` (integrator) | 442 | `_DomainRegistry` (Fibonacci anchor index, ~30 lines), `add_node/add_edge/done`, two buffers (pending_symbols, pending_edges), `_compute_assignment`, peek-before-emit seq seal. | Defensive `_validate_node/_validate_edge` (subsumed by dataclass + protocol allow-set check), `request_subtree` (re-emit known slots — clients can re-snapshot via `replay_since(0)`), `stats()`, `Lock` (single-producer is the contract; the lock is a comfort blanket), tool_hub angle cache (recompute is O(1)). | **~120** |
| `core/layout_engine.py` | 113 | (Older, unrelated to authority — leave aside.) | — | — |
| `handlers/recompute_layout.py` | 132 | Composition root for an out-of-band path. | Mostly scaffolding. | — |
| `infrastructure/layout_pg_store.py` | 133 | Persistence — orthogonal to streaming. | — | — |

**Streaming-essence subtotal:** geometry 150 + protocol 40 + log 50 + wire 40 + integrator 120 = **~400 lines**.

If we drop replay-since (clients always start fresh), drop edge-buffering (build worker emits in order), drop done-event totals: **~200 lines**.

## 4. The SIMPLEST POSSIBLE thing (Turing test)

A single file, ~200 lines, three primitives:

```
1. anchor(domain_idx)        : Fibonacci spiral, pure.       (~20 lines)
2. slot(kind, ctx)            : 9 closed-form formulas.       (~80 lines)
3. emit(seq, kind, payload)   : SSE bytes, fan out to queues. (~30 lines)

Class LayoutAuthority:
   - counts: {(domain, kind) -> int}
   - anchors: {domain -> (x,y)}
   - emitted: set[node_id]
   - pending_symbols: {file_id -> [NodeDelta]}
   - add_node(d): compute slot, emit, flush children if file.
   - add_edge(d): if both endpoints emitted, emit; else discard
                  (build worker emits in dependency order — I5).
                                                              (~70 lines)
```

That is the universal machine for this domain. Everything beyond is decoration.

## 5. What gets CUT and why

| Cut | Reason (Turing-operational) |
|---|---|
| **`layout_authority_scheduler.py` (264 lines)** | The reference integrator is synchronous and non-blocking already. The scheduler is a separate machine that nothing in the emission path uses. A universal machine for a bounded problem (tens of thousands of nodes, single producer) does not need priority displacement; the producer's call stack IS the scheduler. Hamilton 1202 was for an environment where producers compete for cycles — not the case here. |
| **`layout_authority_lod.py` (193 lines)** | LOD is a render-time concern. The authority's job is to stream `(id,x,y)`; the renderer decides what to show. Cutting this enforces SRP. If LOD is needed, 5 lines in the SSE handler: `if kind == "symbol" and hash(id) % stride != 0: continue`. |
| **`Protocol` ABC + INVARIANTS docstring + factory stub (~80 lines)** | Operational test for "is this a layout authority?" = "does it emit `slot`/`edge`/`done` SSE frames in order?" Define the test, not the type. |
| **`replay_since` ring buffer (500k events, ~56MB)** | Last-Event-ID resume is a feature, not the essence. If a client falls behind, full re-snapshot. The buffer is an optimization for an unverified use case. |
| **Defensive validation at the wire layer** | Already validated by dataclass construction + `NODE_KINDS` set membership at `add_node`. Double-validation = belt + braces + spare belt. |
| **`request_subtree` re-emission** | Slots are final (I4/I7). A client wanting a redraw can re-subscribe with `Last-Event-ID: 0`. |
| **`stats()` everywhere** | Observability is an outer layer concern. One counter at `done` event suffices. |
| **`tool_hub_angle` cache, hub_angles dict** | Recompute is O(1). Caching saves ~50 ns at the cost of state. |

## 6. What STAYS (load-bearing)

| Keep | Why it survives reduction |
|---|---|
| **9 closed-form geometry formulas** | This IS the work. Every formula is the simplest machine for "place kind X". |
| **Fibonacci anchor + first-sighting freeze (I7)** | Without anchor stability, slots aren't final. |
| **`pending_symbols` buffer (I3)** | The only ordering invariant the protocol cannot enforce upstream cheaply. |
| **Monotonic seq + emit log** | Required by SSE Last-Event-ID semantics — operational definition of "stream". |
| **3 SSE encoder functions** | The bytes-on-the-wire codec. Cannot be simpler than pipe-split UTF-8. |
| **NodeDelta / EdgeDelta / SlotAssignment dataclasses** | The minimal type-level operational test for "is this a valid event?" |

## 7. Universality assessment

Does this problem require open-ended cases? **No.** Twelve `NODE_KINDS`, fourteen `EDGE_KINDS`, both fixed at protocol-design time. The dispatch table in `compute_slot` is the right shape — a closed sum type, not a plugin host. **No interpreter / no plugin layer is justified.**

## 8. Operational test for "the reduction preserves behavior"

| Concept | Operational test | Pass criterion |
|---|---|---|
| "same layout" | Render fixture graph through old + new authority; diff PNGs. | Pixel-diff < 1% (sub-pixel jitter from float fmt). |
| "same stream" | Same input deltas → byte-identical SSE frames. | `diff` of captured streams empty. |
| "same resume" | Disconnect at seq=K, reconnect with `Last-Event-ID: K`. | Receives K+1..N exactly. |

## 9. Bottom line

| Layer | Now | Reduced essence |
|---|---|---|
| streaming-critical | ~1,500 lines (7 files) | **~400 lines (1 file)** |
| with optional resume + LOD | ~1,500 | ~500 |
| absolute minimum (no resume, in-order edges) | — | **~200 lines** |

**~73% of the layout-authority code is accidental complexity** — scheduler theater, LOD pre-optimization, defensive double-validation, observability scaffolding, an interface protocol that no second implementation will ever exist for. The geometry formulas and the Fibonacci-anchor + pending-symbols buffer are the only non-trivial computation. Everything else is a universal-machine impulse applied to a closed sum type.

## 10. Hand-offs

- Single-program correctness of the reduced integrator → **Dijkstra**.
- "Is the priority scheduler actually load-bearing under N=1M nodes?" → **Erlang** (queueing analysis) or **Fermi** (back-of-envelope: producer rate × event size vs consumer drain rate).
- "Should we keep replay_since at all?" → **Simon** (satisficing on the resume use case).
- Pre-optimization concern about LOD → **Knuth** ("premature optimization").
