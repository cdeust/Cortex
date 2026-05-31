# Ginzburg — Evidential Audit of the Graph-Viz 1M Failures

> Read against the grain. The official explanation of each failure is "the
> algorithm was wrong." The marginal evidence — file boundaries, debounce
> timers, fallback branches, retry loops, comments left behind — tells a
> different story. One assumption resurfaces in every iteration.

## 1. Deliberate testimony (what each rewrite *said* it was fixing)

| # | Approach | Stated cause of prior failure |
|---|---|---|
| 1 | precomputed coords + d3-force | "force-graph re-layouts every payload" |
| 2 | tilemap raster (`dba2f16`) | "force-graph too slow at 1M" |
| 3 | SSE rebuild-on-event | "static tiles lose richness" |
| 4 | SSE first-mount + append | "rebuild-per-event freezes browser" |
| 5 | SSE incremental recompute | "first-mount + append clumps / mis-domains" |
| 6 | tilemap auto-recompute (`4a41aff`) | "stale subscriber stalls server" |

Six algorithms. Six names for one cause. Each treated as fresh.

## 2. Involuntary evidence (the earlobes)

- **2.1 — `ui/unified/js/workflow_graph.js:308–415`** — `prepareTopology()`
  ships with the **client**. `computeSlots` invoked at `:405` after the
  renderer received nodes/edges over the network. Fibonacci anchor
  `phi = π(3 - √5)` (line 323) computed in the browser.
- **2.2 — `tasks/layout-authority/cost-model.md:62–73`** — server port
  copies the same constants verbatim from `workflow_graph.js:308–700`.
  Geometry exists *twice*: client canonical + server port proposed.
- **2.3 — `mcp_server/core/layout_engine.py:47–113`** — invokes
  `igraph.Graph.layout("drl")`. A *third* layout system. Comment line 8:
  "O(N log N) per iteration." cost-model §6 line 102 forbids exactly this.
- **2.4 — `mcp_server/handlers/recompute_layout.py:82–99`** — "skip-if-
  fresh" cache. Exists because the handler is called from three places
  (`/api/recompute_layout` direct, `open_visualization`, tilemap fallback
  at `workflow_graph_tilemap.js:130`). Idempotency patched in because
  authority is unclear.
- **2.5 — `ui/unified/js/workflow_graph_tilemap.js:122–168`** — self-
  healing branch: client gets 503 `no_layout`, *client* calls
  `/api/recompute_layout`, retries `/api/quadtree`. Renderer triggers
  server-side layout.
- **2.6 — `ui/unified/js/polling.js:30–37`** — comment: "phase-driven
  loader owns `lastData` — don't clobber it if it's already been
  populated via /api/graph/phase appends." Two pipelines, one mutable
  state, racing for ownership. The comment is the involuntary confession.
- **2.7 — `ui/unified/js/workflow_graph_bridge.js:107–137`** — debounce:
  "with 10k+ symbol nodes a per-phase render freezes the browser; we
  wait until the stream quiets for 1.2 s before rebuilding the
  simulation." "Rebuilding the simulation" is the smoking phrase: the
  client owns a simulation; every phase append → destroy-and-recreate.
- **2.8 — `workflow_graph_bridge.js:67–73`** — MutationObserver re-
  evicts legacy children that "re-materialise after first render
  (force-graph library and `JUG.setGraphData` both re-mount canvases
  asynchronously)." Two layout systems are physically fighting for one
  DOM node. The observer is the referee. Its existence is the fact.
- **2.9 — `mcp_server/handlers/quadtree_handler.py:33–40`** — returns
  503 `no_layout` when `read_all_positions()` is empty. The endpoint
  that *serves* layout cannot *create* layout; it tells the client to
  call the other endpoint. Same shape as 2.5.
- **2.10 — `mcp_server/server/visualize_bootstrap.py:56–104`** — rsyncs
  the dev tree onto every uv archive root before each spawn. Three
  caches (MCP plugin module snapshot, HTTP graph cache, tilemap Arrow
  buffer), three lifetimes, no coordination. Bootstrap brute-forces it.

## 3. Trace convergence

| Trace | What it reveals |
|---|---|
| 2.1 client `prepareTopology` | renderer computes layout |
| 2.2 server `_geometry` port copying client constants | server *also* computes |
| 2.3 `core/layout_engine.py` igraph DrL | *third* layout system |
| 2.4 `recompute_layout.py` skip-if-fresh | multiple uncoordinated callers |
| 2.5 tilemap → /api/recompute_layout | renderer triggers server layout |
| 2.6 polling.js "don't clobber lastData" | two pipelines race on state |
| 2.7 bridge.js debounce + "simulation" | renderer holds a simulation |
| 2.8 bridge.js MutationObserver | two renderers in one DOM node |
| 2.9 quadtree_handler 503 no_layout | serving ≠ owning |
| 2.10 visualize_bootstrap rsync | three caches, zero owner |

**Structural fact: no single owner of `(node_id) → (x, y)`.** Layout is a
property every layer claims to compute and no layer is contracted to
provide. Five locations: `workflow_graph.js`, `core/layout_engine.py`,
proposed `server/layout_authority_geometry.py`, `layout_pg_store.py`,
the tilemap quadtree.

## 4. The single wrong assumption (smoking gun)

> **"The renderer is responsible for placing nodes."**

Viable at 10k (renderer ran `prepareTopology` per payload). False at 1M.
Each rewrite cured a *symptom* (slowness, freeze, clumping, stall) but
preserved the assumption:

- d3-force ticks → renderer simulates → too slow
- raster tiles → renderer rasterises layout it did not author → ugly
- SSE rebuild → server re-emits, renderer re-simulates → freeze
- SSE append → renderer extends layout from partial graph → **clumps**
  because `workflow_graph.js:317–322` makes `baseR` a function of
  `domains.length` *at call time*. New domain appended later → its anchor
  is computed against an N that includes already-pinned domains → it
  lands on the wrong shell. This is the specific signature of
  "renderer authors layout from incremental data."
- SSE incremental recompute → server tries to take over but renderer
  still holds the simulation; stale subscriber blocks the SSE pipe;
  server cannot release until subscriber drains
- tilemap auto-recompute → renderer *triggers* layout it does not perform
  — the assumption migrated up the stack but did not die

## 5. What naming the assumption demands

Not "a better algorithm." **Invert authority direction:**

1. Layout = server-owned, append-only, monotonically-versioned property
   keyed by `node_id`. Contract: alkhwarizmi.md `add_node`. Invariant:
   dijkstra.md H1/H2 (single producer, seq strict-monotonic).
2. Renderer = passive consumer of `(id, x, y, seq)`. Does not compute,
   simulate, re-derive. **Delete `prepareTopology` and `computeSlots`
   from `workflow_graph.js`** (lines 308–700). MutationObserver becomes
   unnecessary — only one renderer remains.
3. `core/layout_engine.py` (DrL) violates cost-model §6 (O(N log N) per
   iteration disqualified) and the alkhwarizmi `compute_slot` contract
   (closed-form O(1)). **Delete it.** The spiral closed-form stays.
4. `recompute_layout.py` skip-if-fresh: redundant after (1). One caller
   (authority on schema migration). Idempotency patch deletable.

The seam: **WHO computes** must be authority; **WHO renders** must be
passive. Every failure on the trail is a different attempt to keep the
renderer in the authority role while compensating for consequences.

## 6. Hand-offs

- **Eco** — semiotic check on §3: is "no single owner" structural or
  projection? Traces 2.7 (debounce + "simulation") and 2.8
  (MutationObserver) are load-bearing; if either is innocuous the
  inference weakens.
- **Peirce** — formalise §4 as abductive inference from the 10 traces.
- **Engineer** — execute §5: delete `prepareTopology`/`computeSlots` in
  `workflow_graph.js`, delete `core/layout_engine.py`, wire
  `layout_authority` modules per alkhwarizmi + dijkstra.
