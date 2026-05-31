# Clinical Navigation Model

Graph visualization navigation spec for `ui/clinical/`. Sigma.js + graphology renderer.
Implements a "hospital entrance" depth model: structural skeleton first, detail on demand.

---

## 1. Depth Levels

| depth | Label       | Contents loaded                                   | Typical node count |
|-------|-------------|---------------------------------------------------|--------------------|
| 0     | Overview    | Domains only (hub nodes, no edges yet)            | 5–20               |
| 1     | Wings       | L0 + L1 (setup: skills/hooks/agents/commands)     | 50–200             |
| 2     | Departments | + L2 tools                                        | 200–500            |
| 3     | Corridors   | + L3 files                                        | 500–2 000          |
| 4     | Rooms       | + L4 discussions                                  | 2 000–10 000       |
| 5     | Beds        | + L5 memories                                     | 10 000–100 000     |
| 6     | Atoms       | + all L6:\<slug\> symbol sub-phases (dynamic)     | 100 000+           |

---

## 2. State Machine

```
State {
  current_depth : 0..6          // what is rendered
  target_depth  : 0..6          // destination of an in-flight transition
  transition    : idle | zooming_in | zooming_out
  loadedPhases  : Set<string>   // phases whose nodes are in the graph
  pendingPhases : Set<string>   // phases currently being fetched
  cameraZ       : float         // Sigma camera ratio (1.0 = default)
  focusedNode   : string|null   // node id with open chain-of-call panel
}
```

### Transitions

| Trigger                   | Guard                         | Action                                        |
|---------------------------|-------------------------------|-----------------------------------------------|
| scroll-down / pinch-in    | target_depth < 6              | target_depth++; fetch_depth(target_depth)     |
| scroll-up  / pinch-out    | target_depth > 0              | target_depth--; fade_out_depth(target_depth+1)|
| double-click on node      | node.depth < 6                | target_depth = node.depth + 1; center on node |
| node single-click         | —                             | open chain-of-call panel; set focusedNode     |
| Escape / panel-close      | focusedNode != null           | close panel; focusedNode = null               |
| SSE done event            | —                             | source.close(); mark full_ready               |
| quadtree 503              | —                             | fall back to circular layout; retry after 5s  |

Zoom triggers increment/decrement `target_depth` by 1. Camera ratio is adjusted
continuously by Sigma's built-in wheel handler; depth transitions fire only at
discrete threshold crossings (cameraZ crosses a per-depth breakpoint table).

---

## 3. Phase Loading per Depth

```
depth 0 : fetch phase "L0"
depth 1 : fetch phase "L1"
depth 2 : fetch phase "L2"
depth 3 : fetch phase "L3"
depth 4 : fetch phase "L4"
depth 5 : fetch phase "L5"
depth 6 : enumerate Object.keys(progress.phases)
            .filter(k => k.startsWith('L6:'))
          fetch each L6:<slug> phase sequentially (or parallel, max 3)
```

Guards before every fetch:
- `loadedPhases.has(phase)` → skip (already in graph)
- `pendingPhases.has(phase)` → skip (in flight)

Both sets are updated atomically before the fetch fires.

Cold-start sequence (app init):
1. `GET /api/graph/progress` → record all phase keys
2. `GET /api/recompute_layout` → fire-and-forget; don't block render
3. `GET /api/graph/phase?name=L0` → seed graph
4. `GET /api/graph/phase?name=L1` → load depth-1 immediately (default landing = depth 1)
5. Subscribe to `GET /api/graph/events` (SSE) for remaining phases as user zooms

---

## 4. Visibility Rules

```
fade_in  : opacity 0 → 1 over 300 ms (CSS transition on Sigma node/edge attributes)
fade_out : opacity 1 → 0 over 200 ms, then remove from graph after transition
```

| When zooming IN to depth N   | Nodes at depth N    | fade_in                              |
|                              | Nodes at depth N-1  | remain, label hidden at small ratio  |
|                              | Nodes at depth <N-1 | remain visible (structural skeleton) |

| When zooming OUT to depth N  | Nodes at depth >N   | fade_out then removeNode             |
|                              | Nodes at depth <=N  | remain                               |

Node attributes controlling visibility:
```js
{ depth: number, visible: boolean, opacity: number }
```

Edges are shown only when both endpoint nodes are currently visible.
Hub/structural nodes (degree > threshold) are never faded out regardless of depth.

---

## 5. Hit-Test Strategy per Depth

| depth | Cursor radius | Label policy                              | Node size     |
|-------|---------------|-------------------------------------------|---------------|
| 0–1   | 20 px         | Always shown (few nodes)                  | 18–30 px      |
| 2     | 14 px         | Shown when camera ratio > 0.6             | 10–20 px      |
| 3     | 10 px         | Shown on hover only                       | 6–14 px       |
| 4–5   | 6 px          | Shown on hover only                       | 3–8 px        |
| 6     | 4 px          | Hidden; tooltip on hover                  | 2–5 px        |

Sigma's `hoverRenderer` is used for hover labels at depths 3+.
Cursor radius is set via `Sigma({ hoverRadius: <value> })` per-depth or computed
from current camera ratio: `radius = base / cameraRatio`.

---

## 6. Pan / Zoom Behaviour

- **Free pan**: mouse-drag at any depth; no bounds restriction.
- **Zoom (camera ratio)**: Sigma wheel handler controls camera ratio continuously.
- **Depth threshold table**: depth transition fires when camera ratio crosses:

```js
const DEPTH_THRESHOLDS = [
  { depth: 0, zoomOut: Infinity, zoomIn: 0.9 },
  { depth: 1, zoomOut: 1.1,      zoomIn: 0.6 },
  { depth: 2, zoomOut: 0.7,      zoomIn: 0.35 },
  { depth: 3, zoomOut: 0.4,      zoomIn: 0.18 },
  { depth: 4, zoomOut: 0.22,     zoomIn: 0.08 },
  { depth: 5, zoomOut: 0.10,     zoomIn: 0.035 },
  { depth: 6, zoomOut: 0.045,    zoomIn: 0.0 },
];
```

Depth transitions are debounced (150 ms) to avoid thrashing on fast scroll.

Double-click on a node:
1. Sigma camera animates to center on the clicked node.
2. After animation settles (300 ms), depth increments if node.depth >= current_depth.

---

## 7. Chain-of-Call Panel

Single-click on any node opens a side panel (slide-in from right, 360 px wide).
The main graph view is NOT modified — no new nodes are added.

Panel contents:
- Node label + kind + depth badge
- Outbound edges (calls / depends-on)
- Inbound edges (called-by / depended-by)
- (future) full chain: a mini Sigma canvas inside the panel rendered from a
  filtered subgraph of the already-loaded graph data.

The chain panel is a separate concern: `chain-panel.js` owns it entirely.
It reads from the graphology `Graph` instance (shared reference, read-only).

---

## 8. Returning User / Session Restore

- **Default landing**: depth 1 (Wings view — domains + setup structure visible).
- **Session restore**: `localStorage.getItem('cortex.clinical.depth')` on load.
  If present and in range [0, 5], restore to that depth (depth 6 is never restored
  automatically — too costly on cold start).
- Camera position is NOT restored (layout may have changed between sessions).
- `focusedNode` is NOT restored (panel state is ephemeral).

On every depth change: `localStorage.setItem('cortex.clinical.depth', depth)`.

---

## 9. Error Handling

| Failure                      | Recovery                                                          |
|------------------------------|-------------------------------------------------------------------|
| `/api/graph/phase` 5xx       | Show status bar message; retry once after 2 s; mark phase failed  |
| `/api/quadtree` 503          | Use graphology circular layout; poll every 5 s until 200          |
| SSE connection drop          | Reconnect once; if second drop show "graph incomplete" badge       |
| `addNode` duplicate (Sigma)  | Guard with `loadedPhases` + `pendingPhases`; never reaches Sigma   |
| Empty phase (0 nodes)        | Mark loaded; no-op; do not show error                             |
