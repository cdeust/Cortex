# Jobs — The Integrated Experience IS the Spec

> The user has shipped six "working" iterations. Each passed a technical
> metric (FPS, payload size, no-crash, server-uptime). All six failed the
> only spec that matters: **the user clicks "open visualization" and sees
> their actual neural graph build itself in front of them, traceable end
> to end.** Component metrics lied. Experience-level spec did not exist.
> This file is the executable spec.

## 1. The user's words, taken literally as the spec

Two phrases, quoted from the user's frustration. They are not poetry;
they are the acceptance criteria:

1. **"node appearing without stopping until finished loading all of them"**
   — a continuous, monotonic, never-stalling stream from t=0 until the
   build worker finishes. No batch flushes. No "wait, then dump." No
   freeze, then catch-up. **Continuous monotonic emission** is the spec.

2. **"real neural graph showing data with link to what it comes from
   and where it goes to"** — every node visible on screen MUST be
   traceable: hover/click → `(node_id, source_path, kind, domain,
   parent_id, edges_in, edges_out)`. The graph is not decoration; it
   is *navigation over the actual data*. **Provenance per node** is
   the spec.

Anything that ships without (1) AND (2) simultaneously fails. Trade-offs
("we have continuity but no provenance," "we have provenance but it
freezes") are design failures, not acceptable engineering compromises.

## 2. Executable spec — what happens when the user clicks "open visualization"

Time is measured from the click. Each row is testable end-to-end.

| t | What the user MUST see | What is NOT acceptable |
|---|---|---|
| **0 ms** | Click registers. Window/tab opens within one frame (≤16 ms). | Spinner-only. "Loading…" with no graph frame. Tab opening empty for >100 ms. |
| **0–500 ms** | Empty canvas with axis/legend/domain anchors visible (the 11 domain hubs at their Fibonacci anchors, even with zero nodes). The "skeleton" of the map. SSE connection established, status indicator shows "live". | Blank white screen. "Connecting…" modal. Anything that looks like the page failed to load. |
| **500 ms** | First nodes start appearing. Setup hubs and tool hubs (the small fixed set, ~70) are placed and visible. User can already see the shape of their workspace. | Still a blank canvas. A "preparing layout…" message. Loading bar at 0%. |
| **0.5–2 s** | Nodes stream in continuously. The user sees them *appear*, one after another, at deterministic positions — no jumping, no rearrangement, no flash-of-clumped-then-spread. Frame rate stays ≥30 fps; UI stays interactive (pan, zoom, hover). | Burst-then-pause. Visible "tick" of the force simulation. Nodes appearing at (0,0) then teleporting. Browser tab beachball. |
| **2 s** | First files and their attached symbols are visible around their tool/domain anchors. Hovering any visible node shows the tooltip with `node_id`, `kind`, `source_path`, `domain`. | Hover does nothing. Tooltip shows "id: 42" with no provenance. Click does not select. |
| **2–10 s** | Streaming continues monotonically. Edges are drawn as their endpoints appear; if an edge arrives before its target, it waits silently in a buffer (no red error, no flicker) and is drawn the instant the target lands. User can click any node and see incoming/outgoing edges highlighted; clicking an edge endpoint navigates the camera. | Edges drawn to (0,0). Edges flickering as endpoints reseat. Console errors. "Edge target missing" toasts. |
| **10 s** | Roughly 10⁵–10⁶ nodes placed (Cortex repo scale). The user can already work — search, filter, navigate by domain — without waiting for completion. The status indicator shows "live: N nodes, M edges, building…". | The UI being read-only until the build "finishes." Search disabled until 100%. A modal blocking interaction. |
| **60 s** | Build worker has finished or is finishing. The status indicator transitions to "live: N nodes, M edges, complete". The graph is identical (deterministic) to what the user will see if they reload. Memory footprint stable. No background thrash. | The browser tab becoming sluggish. Memory growing unbounded. The status never reaching "complete." A "rebuilding…" loop. |
| **anytime ≥0.5 s** | Hover any node → tooltip in <50 ms with `(node_id, kind, source_path, domain, parent_id)`. Click → side panel showing edges in/out with clickable navigation. Camera follows. | Hover lag >200 ms. Tooltip showing only `id`. No way to get from a node back to its file. |
| **on disconnect** | Lost SSE connection → status "reconnecting…", graph remains visible and interactive on what was already received. Reconnect resumes from `Last-Event-ID`; gap is replayed silently. | Graph clears on disconnect. Page refreshes itself. User loses scroll position. |

## 3. The integration boundary map — and where every iteration leaked

| Boundary | Side A | Side B | Visible to user as friction? | Owner today |
|---|---|---|---|---|
| Click → window open | `open_visualization` handler | browser process | **Yes (blank tab >100 ms)** | nobody |
| Window open → first frame | bootstrap rsync (`visualize_bootstrap.py:56–104`) | HTTP server | **Yes (cold start >2 s)** | nobody |
| HTTP server → SSE | `http_viz_server` | `EventSource` client | **Yes — no consumer wired today** (Einstein Frame 9) | nobody |
| SSE event → canvas paint | `format_slot` bytes | `workflow_graph_tilemap.js` | **Yes — field name mismatch `slot.id` vs `slot.node_id`** (Pólya item 1) | nobody |
| add_node → slot emission | scheduler P4 deque | `layout_authority.py` | **Yes — silent drops when no integrator drains** (Einstein Frame 2) | **MISSING** |
| node placement → edge draw | layout authority | edge buffer | **Yes — edges to (0,0) under reseat** (Einstein Frame 10) | nobody |
| node identity → provenance | `SlotAssignment` (5 fields) | tooltip | **Yes — bytes layer drops everything except (id,x,y,kind,dom)** | nobody |

**Every boundary is unowned. Six iterations sanded the same seam from
six different sides because no single person owned the seam itself.**

## 4. All-dimensions-simultaneously check (current state)

| Dimension | Bar | Current | Pass? |
|---|---|---|---|
| **Continuous emission** | Nodes appear monotonically; no burst-then-pause; no freeze | Force-sim ticks, debounce-rebuild, SSE-clumping all violate | **NO** |
| **Provenance per node** | Hover shows `(id, kind, path, domain, parent, edges)` | Tilemap raster has no `node_id` at all (pixels only) | **NO** |
| **Interactive within 2 s** | Pan/zoom/hover responsive while streaming | Browser freezes on per-phase rebuild (`bridge.js:107`) | **NO** |
| **Deterministic positions** | Same input → same `(x,y)` across reloads | Append-clumping bug (Ginzburg §4: `baseR(domains.length)` recomputed) | **NO** |
| **Beautiful (no flicker)** | No node teleports; no edge to (0,0) | Reseat-on-late-parent draws orphans (Einstein Frame 10) | **NO** |
| **Robust (reconnect)** | Loss of SSE → silent replay from `Last-Event-ID` | No EventSource consumer exists | **NO** |
| **Bounded memory** | Working set stable on the box | Three uncoordinated caches (visualize_bootstrap.py:56–104) | **NO** |

**Zero of seven dimensions pass.** "It works on my benchmark" is not
"it works." Every prior ship was a falsification of "it just works."

## 5. The seam that must be eliminated to make this shippable

The user owns the *whole* stack — Python server, JS renderer, Postgres
store, SSE wire, layout geometry. There is no external vendor. The
seams exist only because **no module owns the integrated experience
end-to-end.** Vertical integration here is not a business strategy; it
is the correctness mechanism.

**Single owner: `layout_authority.py` (Pólya item 2; ~150 LOC).** It
owns:
1. The counter map `(domain_id, kind) → int`.
2. The pending-parent buffer (I3) and pending-edges buffer (I5).
3. The single producer thread that pops the scheduler, calls
   `compute_slot`, and emits via `log.emit('slot', bytes)`.
4. The SSE handler is a passive subscriber; the renderer is a passive
   subscriber. Neither computes layout. Neither rebuilds simulations.

When this module exists and owns the seam, every row of §2 becomes
testable, every dimension of §4 becomes measurable, and the user's two
sentences become falsifiable claims a CI test can enforce.

## 6. Edit ruthlessly — what must be cut to ship the integrated experience

| Cut | Why |
|---|---|
| `core/layout_engine.py` (igraph DrL) | Ginzburg §5.3: O(N log N), violates cost-model §6, third layout system |
| `prepareTopology` + `computeSlots` in `workflow_graph.js:308–700` | Ginzburg §5.2: renderer must NOT author layout |
| MutationObserver in `workflow_graph_bridge.js:67–73` | Ginzburg 2.8: only exists because two renderers fight; one renderer → no referee needed |
| Debounce timer in `workflow_graph_bridge.js:107–137` | Becomes obsolete: no per-phase simulation rebuild if renderer is passive |
| Skip-if-fresh cache in `recompute_layout.py:82–99` | Becomes obsolete: one caller (schema migration), not three |
| `polling.js` "don't clobber lastData" branch | Two pipelines collapse to one when authority is single-writer |

The product is what remains after the cut, not what was added in each
iteration.

## 7. The "it just works" CI test (acceptance gate)

A single end-to-end test must pass before the next ship:

```
GIVEN a clean Cortex DB seeded with this repo (≈30k nodes)
WHEN the user invokes `cortex:open_visualization`
THEN within 500 ms a tab opens with the 11 domain anchors visible
AND within 2 s the first 1000 nodes are visible at deterministic positions
AND streaming continues monotonically with frame rate ≥30 fps
AND every visible node responds to hover within 50 ms with full provenance
AND every edge connects two already-visible nodes (or is buffered, never drawn at (0,0))
AND on completion the graph is byte-identical to a reload
AND on SSE disconnect+reconnect the graph state is preserved and the gap replayed
```

If any clause fails, the build does not ship. "Fix it later" is not
accepted because every prior "fix it later" became another iteration in
§1 of Ginzburg.

## 8. Hand-offs

- **engineer**: build `layout_authority.py` per Pólya §6 in the order
  given. Implement §7 as a Playwright end-to-end test before declaring
  done.
- **Curie**: instrument §2's t-table (0/0.5/2/10/60 s) so each row
  becomes a measured number, not an aspiration.
- **Hamilton**: SSE reconnect+replay path (§2 last row, §7 last clause)
  is the resilience gate.
- **Liskov**: SSE consumer contract — any new renderer (3D map,
  minimap, graph-RAG UI) must be substitutable behind the same
  `(id, x, y, kind, domain)` byte stream without touching the authority.
