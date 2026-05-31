# Sub-Graph Drill-Down

Spec for node-click chain-of-call / chain-of-action view in `ui/clinical/`.

---

## 1. Interaction Model: Side Panel

Single-click opens a **slide-in side panel** (360 px, right edge).
The main canvas is NOT modified — no nodes added, no layout disturbed.

A modal blocks the canvas and prevents comparing multiple nodes.
A routed page loses camera state and the loaded phase set (cold-start
rebuild on back). A side panel preserves both: main graph stays live,
camera is untouched, multiple nodes can be inspected in sequence.

- **Open**: click node → panel slides in (CSS `translateX`, 250 ms).
- **Replace**: click different node while panel open → content swapped in-place.
- **Close**: Escape, canvas click outside a node, or panel × button.

Module: `ui/clinical/chain-panel.js` (owns all panel DOM; never touches Sigma).

---

## 2. Data Source

**Primary: `GET /api/graph/chain`** (already live on the branch).

```
GET /api/graph/chain?id=<node_label>&depth=<1..8>&type=<causal|impact|call>
```

Response: `{ mermaid, node_count, edge_count, depth_reached, truncated, seed }`.
Server caps at 150 nodes/edges combined; `truncated` flag signals overflow.
Never raises — missing entity returns a valid not-found body.

**`type` parameter per tab:**

| Tab    | `type=`  | Direction | Meaning                             |
|--------|----------|-----------|-------------------------------------|
| Causal | `causal` | incoming  | What caused / depends on this node  |
| Impact | `impact` | outgoing  | What this node affects downstream   |
| Call   | `call`   | both      | Full neighbourhood (calls + callers)|

**Secondary: local graphology `Graph` instance** (zero latency, depth = 1).
Immediate neighbours are read via `graph.neighbors(id)` before the fetch
resolves. Neighbour list appears instantly; Mermaid section populates after.

No new server endpoint is required for the initial implementation.

---

## 3. Sub-Graph Rendering: Mermaid Inside the Panel

The chain diagram renders as **Mermaid flowchart SVG** inside the panel DOM,
not as a second Sigma instance.

A second Sigma WebGL context risks context-lost events — browsers cap
contexts at 8–16 and the main instance already strains GPU memory at depth 6.
The chain DAG is small (≤ 150 nodes); Mermaid renders it in < 50 ms with
no layout step, produces accessible SVG, and needs no additional render loop.

Add `mermaid.min.js` to `ui/clinical/vendor/` during scaffold. Initialise
lazily on first panel open: `mermaid.initialize({ startOnLoad:false, theme:'dark' })`,
then call `mermaid.run({ nodes:[divEl] })` each time the Mermaid section updates.

---

## 4. Per-Kind Sub-Graph Variants

| Node kind                              | Default tab | Notable edges shown                        |
|----------------------------------------|-------------|---------------------------------------------|
| `memory`                               | Causal      | Temporal causal chain; what preceded/followed |
| `symbol`                               | Call        | `defined_in` file; `calls` outbound; `member_of` |
| `file`                                 | Impact      | `tool_used_file` (tool accessors); symbols inside |
| `discussion`                           | Causal      | Linked memories, entities; `has_discussion` to domain |
| `domain`                               | Impact      | Skills, hooks, tool hubs, memories in domain |
| `skill` / `hook` / `agent` / `command` | Call        | Bidirectional invocation neighbourhood      |
| `entity`                               | Causal      | Entity knowledge graph BFS                  |
| all others                             | Call        | Generic bidirectional neighbourhood         |

Tab selection sets the `type` query parameter automatically; user can switch.

---

## 5. Back-Navigation and Depth Resume

No router — the panel is ephemeral UI state. Closing returns to the exact
main-graph state: same camera, same loaded phases, same depth. Nothing to undo.

Clicking a neighbour entry inside the panel performs a **panel-replace**
(not navigation). A history stack (max depth 5) enables stepping back:

```js
// chain-panel.js
const _history = [];   // [{nodeId, tab}]

function openNode(id, tab) {
  _history.length < 5 || _history.shift();
  _history.push({ nodeId: _current, tab: _currentTab });
  _render(id, tab);
}
function panelBack() {
  if (!_history.length) { closePanel(); return; }
  const p = _history.pop();
  _render(p.nodeId, p.tab, /* pushHistory= */ false);
}
```

`←` back button appears in the header whenever `_history` is non-empty.
The main graph's `current_depth` and camera are never touched by panel code.

---

## 6. Error Handling

| Failure                          | Recovery                                                 |
|----------------------------------|----------------------------------------------------------|
| `/api/graph/chain` non-2xx       | Show "chain unavailable" in Mermaid section; neighbour   |
|                                  | list (local) remains visible. `.catch()` on every fetch. |
| `truncated: true`                | Show "diagram capped at 150 nodes" badge in panel.       |
| Mermaid render error             | Catch promise rejection; show raw source in `<pre>`.     |
| Node has no entity match         | Hide Mermaid section; show neighbour list only.          |

---

## 7. Open Questions

1. **Node ID vs. label lookup.** `/api/graph/chain` resolves by entity name.
   A `?node_id=` parameter resolving by internal graph ID would be more
   precise and avoid silent mismatches when display label differs from
   entity name. Low server cost to add; decision deferred.

2. **Mermaid vendor bundle.** `mermaid.min.js` (≈ 800 KB) is not yet in
   `ui/clinical/vendor/`. Confirm acceptable offline bundle size before
   scaffold step downloads it.

3. **File panel + L6 symbols.** `defined_in` symbol edges only exist once
   L6 phases load (depth 6). Decide: wait for L6 or hide the symbols
   sub-section when L6 is not yet loaded.
