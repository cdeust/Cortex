# Layout Authority — Alexander Pattern Catalog

A pattern language for the Cortex layout authority (geometry + protocol + wire
+ scheduler + log). Each pattern names a tension the code resolves; the
generative sequence at the end records the order they must be applied in.

## Pattern 1 — Closed-Form Slot

- **CONTEXT.** A node arrives and must be placed at `(x, y)` before any
  consumer can render it; the slot is stable for the node's lifetime (I2).
- **PROBLEM.** Iterative layout (force ticks, sibling sweeps, spatial-index
  rebuilds) is at least O(N log N) per tick. At N = 10⁹ in 1–2 s the budget
  collapses to ~1 ns/node (~3 cycles) — no iteration fits.
- **FORCES.** Need a slot now; cannot read sibling state at insert; visual shape must match the months-tuned `workflow_graph.js`; memory must stay flat.
- **SOLUTION.** `(x, y)` is a pure function of `(domain_anchor, kind, idx, total_in_kind)` plus, for symbols, the parent file's slot. Per insert: one counter bump, one trig call. Every helper in `layout_authority_geometry` (`slot_for_setup`, `slot_for_tool_hub`, `slot_for_file`, `slot_for_discussion`, `slot_for_memory`, `slot_for_mcp`, `slot_for_symbol`) is O(1) with no allocation past the return tuple. Constants copied verbatim from the JS — a port, not a redesign.
- **RELATED.** Pattern 2 (stability), Pattern 4 (528-byte footprint).

## Pattern 2 — Slot-Stable Coordinate (no retroactive reseat)

- **CONTEXT.** The build worker emits in arbitrary order — a file before its tool_hub, a member before its domain hub.
- **PROBLEM.** "Replace previous (x, y) when better parent info arrives" sounds reasonable but breaks every consumer: clients render position once, edges are drawn between placed endpoints, Last-Event-ID resume becomes ambiguous.
- **FORCES.** Out-of-order arrival is real (I4, I7); recompute is forbidden; visual shape must still be correct in the common case.
- **SOLUTION.** Once placed, a slot is FINAL until an explicit `request_subtree(domain_id)` invalidates it. Missing parent context falls back to the domain anchor (or canvas center) — finite, deterministic, topologically coherent. The single re-emission lane is `request_subtree`, scheduled as P6 and coalesced.
- **RELATED.** Pattern 1 (determinism), Pattern 5 (replay), Pattern 3 (defers reseats to P6).

## Pattern 3 — Priority-Displaced Drop (Hamilton 1202)

- **CONTEXT.** Producer fires `add_node` / `add_edge` faster than the authority emits — a 10⁹-node burst saturates everything.
- **PROBLEM.** Blocking back-pressure stalls the producer; unbounded queues OOM; uniform shedding loses topologically critical hubs first because they are rare relative to symbols and edges.
- **FORCES.** Producer must NEVER block (I6); 8 MB ceiling; not every node is equal — losing a domain hub orphans thousands while losing 10% of symbols is invisible.
- **SOLUTION.** Seven priority lanes in `PriorityScheduler` (P0 domain → P6 subtree) with hand-derived caps (P0=1k, P1=1k, P2=16k, P3=32k, P4=64k, P5=128k, P6=100). `submit()` is non-blocking and returns False on cap with a per-priority dropped counter. `pop()` always drains the lowest-numbered non-empty queue. P6 reseats are coalesced (linear scan over a 100-cap deque) so a viewport drag at 10 req/s collapses to one pending entry.
- **RELATED.** Pattern 4 (ceiling), Pattern 2 (safe shedding).

## Pattern 4 — Bounded Producer State (counters, not graphs)

- **CONTEXT.** Authority sits between build worker and renderer; must scale to 10⁹ nodes within 8 MB working set.
- **PROBLEM.** Any structure that grows with N (node list, edge list, spatial index) blows the ceiling past 10⁵.
- **FORCES.** State must be enough to compute `compute_slot` for the *next* arrival — nothing more is permitted.
- **SOLUTION.** State is `counter[(domain_id, kind)] -> int` plus a per-domain anchor cache, a per-tool-hub angle cache, and a parent-file-slot cache for symbols only. `cost-model.md` §3 bounds this at ~528 bytes for 11 domains × 6 kinds; the symbol cache is bounded by the visible window, not by N. Edges and full node payloads NEVER live here — renderer owns those buffers, log owns byte payloads, authority owns only what the next slot needs.
- **RELATED.** Pattern 1 (sufficiency), Pattern 3 (burst protection), Pattern 6 (the one place state grows with stream length, ring-buffered).

## Pattern 5 — Monotone Seq Resume (Last-Event-ID)

- **CONTEXT.** SSE clients disconnect (network, tab sleep, refresh) and want to resume without re-streaming the whole graph.
- **PROBLEM.** Per-build-reset seq numbers collide across reconnects: a client holding `Last-Event-ID: 12345` from build A would silently consume 12345+ from build B as if they were the same stream.
- **FORCES.** `reset()` runs at every fresh build; seq must distinguish "you missed events" from "fresh stream"; the buffer cannot keep all history.
- **SOLUTION.** `_event_seq` is a *global* monotonic counter that does NOT rewind across `reset()` — the explicit prose-vs-code reconciliation in `layout_authority_log.reset` (prose wins). `replay_since(since)` returns newer events; a gap (`oldest_seq > since + 1`) signals snapshot fallback. The 500k-event ring buffer is a window onto history, not the source of truth.
- **RELATED.** Pattern 6 (substrate), Pattern 2 (replayed slot meaningful).

## Pattern 6 — Pre-Encoded Pipe Frame (zero-reparse fan-out)

- **CONTEXT.** One producer thread, many SSE subscribers, ~1M slot events/s peak. The same bytes go to every subscriber.
- **PROBLEM.** Re-encoding per subscriber (browser `JSON.parse` ~1 µs for a 5-field object; per-socket format-encode-write) burns producer budget.
- **FORCES.** Encode-once must compose with SSE framing, the bounded ring buffer, Last-Event-ID resume, sub-pixel formatting (`:.1f` at FILE_R = 220 saves ~3–4 B/event), and delimiter-safety in user-controlled ids.
- **SOLUTION.** `layout_authority_wire.format_slot` returns finished `bytes`: `id: <seq>\n event: slot\n data: <id>|<x:.1f>|<y:.1f>|<kind>|<domain_id>\n\n`, validated for `|`, `\n`, `\r`, NaN/inf at the boundary. The log stores the frame; `_fan_out` calls `put_nowait(event)` per subscriber with the same bytes; handlers write directly to socket. Pipe, not JSON, because `String.split('|')` parses ~4× faster than `JSON.parse`. The payload IS the cache.
- **RELATED.** Pattern 5 (seq embedded in frame, resume is frame-level).

## Generative sequence

1. **Closed-Form Slot (1)** — O(1) per node, 528-byte footprint; nothing else
   fits the budget.
2. **Bounded Producer State (4)** — counters as the *only* state, ruling out
   node/edge lists and spatial indices.
3. **Slot-Stable Coordinate (2)** — `(x, y)` final; works because (1) made
   every slot deterministic.
4. **Priority-Displaced Drop (3)** — back-pressure safe *because* (2) means a
   dropped symbol never corrupts its file.
5. **Pre-Encoded Pipe Frame (6)** — stability meaningful only given (2);
   volume survivable only given (3).
6. **Monotone Seq Resume (5)** — replay works because (6) keeps the frame
   intact and (2) keeps slot meaning intact across reconnects.

Reordering breaks the language. Choosing (3) before (1) yields priority lanes
for an iterative placer that cannot meet the per-node budget at all.
