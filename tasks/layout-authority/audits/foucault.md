# Genealogy of `workflow_graph_bridge.js` — Foucault Audit

> "What is questioned is the way in which knowledge circulates and functions, its
> relations to power. In short, the *régime du savoir*." — Foucault, *The Subject
> and Power* (1982)

## Target practice

The "destroy + remount on every `state:lastData` event" pattern in
`ui/unified/js/workflow_graph_bridge.js`. It is currently the load-bearing source
of every freeze in this session. It appears, to the reader of the file, as
common-sense engineering: "of course you tear down the old D3 simulation before
mounting the new one — that's how you avoid leaks." The genealogy will show
that this *common sense* was constructed in 13 days, by three commits, under
specific contingent pressures that no longer obtain.

## Genealogy — three commits, three power arrangements

| Date (2026) | SHA | Arrangement that produced the code | What was excluded |
|---|---|---|---|
| 04-22 09:10 | `8371b9d` | A *legacy force-graph renderer* (`graph.js` + a CDN-loaded `force-graph` library) already owned `#graph-container` and animated continuously. The new D3 workflow graph had to *coexist* with it inside the same DOM host. The bridge was born as a **deportation officer**: detect "is this a workflow_graph.v1 payload?", and if yes, evict the legacy children, pause the legacy animation, and mount D3 in a wrapper. `destroy()` here meant *destroy the previous D3 handle so the new payload's force sim doesn't fight the old one*. | A *single-renderer* world. Replacing the legacy pipeline outright was politically impossible: `polling.js`, `detail_panel`, `controls`, `monitor` all spoke `JUG.setGraphData` / `JUG.getGraph`. The bridge was a *truce*, not a design. |
| 04-22 11:30 | `e98e1e5` | Twelve hours later, the legacy renderer was *retired in spirit but not in law*: the CDN was commented out, `window.ForceGraph` became an inert Proxy, `workflow_graph_shims.js` stubbed the JUG surface. **Yet the bridge gained a `MutationObserver` that continuously re-removes legacy children.** The observer is a monument to a war that ended that morning. The legacy renderer no longer mounts canvases — but the bridge still patrols the host as if it might. | The opportunity to *delete the bridge*, since its raison d'être (coexistence with force-graph) had just been removed. Instead the bridge was *hardened* — the `removeChild` was upgraded from `display:none`, the observer was added "in case Safari re-mounts." The colonial garrison stayed after independence. |
| 04-22 23:40 | `be606fb` | The phase-driven loader landed (`/api/graph/phase?name=L0…L6:<proj>`). Each phase publishes nodes; `polling.js` writes them to `JUG.state.lastData`; the bridge's listener fires *per phase*. Now, on a 10k-symbol project, the listener fires 6–20 times in 30 seconds, each time **destroying the running D3 force simulation and rebuilding from scratch**. The author noticed the freeze and added a 400 ms / 500 ms / 5000 ms three-tier debounce — a rhetorical gesture toward incremental update without performing one. | An *append/diff* protocol: receive phase deltas, add the new nodes to the running simulation, let it relax. This was *unspeakable* because the bridge's discourse was already organized around the verb `render(data)` — a total-state replacement primitive inherited from the 04-22 morning truce. |

## Discourse formation — what the bridge is allowed to say

| Rule | Description | Effect |
|---|---|---|
| Authorized speakers | Only `state:lastData` events. The phase loader cannot speak directly to D3. | Every phase boundary becomes a full re-render. |
| Legitimate verb | `render(data)` — a total-state replacement. There is no `appendNodes(delta)`. | Incremental layout is unsayable. |
| Legitimate evidence | "Did the user freeze?" → answer with debounce constants. | Algorithmic cause (O(N) re-simulate per phase) is invisible — only its *symptom* (jank) is discussable, and only via wait-time tuning. |
| Excluded vocabulary | "Layout authority", "stable simulation", "phase-aware update", "tile pipeline owns layout". | The architectural alternative cannot be named within the file. |
| Boundaries | The bridge is forbidden from knowing what `JUG.renderWorkflowGraph` does internally — it must treat it as a black box with `destroy()`. | The simulation cannot be *kept alive* across data updates because the discourse forbids knowing whether it could be. |

## Power/knowledge analysis

- **Knowledge produced:** "Rendering 10k nodes in the browser is hard; you must debounce." This appears as a neutral engineering fact.
- **Produced by:** the legacy-force-graph regime, which only ever knew total replacement (`setGraphData(nodes, edges)` is itself a destroy-and-remount primitive — ForceGraph's API has no append).
- **Serves:** the convenience of leaving `polling.js` and the JUG event bus untouched. The bridge absorbs all complexity so the rest of the codebase keeps speaking the legacy idiom.
- **Excludes:** the knowledge that D3 v7's force simulation is *explicitly designed for incremental updates* — `simulation.nodes(newArr)` adds nodes without resetting α, and `alpha(0.3).restart()` warm-resumes. The bridge's `destroy()`-then-mount loop *throws away free physics every 500 ms* because the discourse cannot see this option.

## Archaeology of assumptions

| Assumption baked into the bridge | Makes possible | Would change if false |
|---|---|---|
| "A renderer owns its DOM exclusively; if data changes, the renderer is replaced." | The `destroy + ensureWrapper + new render` cycle. | Renderer becomes a *long-lived service* with `update(delta)` — no destroy on data event. |
| "`state:lastData` is the canonical, monolithic source of truth." | The whole-payload re-render on every phase. | Phase events become first-class: bridge subscribes to `state:phaseAppended` and forwards a *delta*, never the whole payload. |
| "The bridge cannot trust the renderer to be alive between events." | Defensive `if (_handle) _handle.destroy()`. | The renderer *guarantees* liveness; bridge becomes a one-shot mounter, never a re-mounter. |
| "Layout is computed in the browser, on the main thread, every time data arrives." | The freeze. The freeze is the *necessary symptom* of this assumption. | If layout authority moves to the server (the tilemap pipeline already exists in this repo: `workflow_graph_tilemap.js`, `layout_worker_main.py`, `layout_pg_store.py`), the bridge's destroy/remount becomes irrelevant — tiles are streamed, not recomputed. |

## Subject positions the discourse creates

| Position | Occupied by | Authority | Constraint |
|---|---|---|---|
| The Bridge | `workflow_graph_bridge.js` | Decides *whether* to render and *when*; owns the wrapper DOM. | Cannot decide *how* — must call `JUG.renderWorkflowGraph` as opaque oracle. |
| The Renderer | `JUG.renderWorkflowGraph` | Owns layout math, force sim, canvas/SVG paint. | Treated as stateless from the bridge's perspective; loses identity on every event. |
| The Polling Loop | `polling.js` | Sole publisher of `state:lastData`. | Cannot signal "this is an append, not a replace" — the channel has only one verb. |
| The User | (silent) | Sees freezes. | Has no vocabulary in the codebase to demand "incremental update" — only "make it faster", which the debounce knobs pretend to address. |

## Contingency finding

The destroy/remount pattern is **not** common-sense engineering. It is a fossil
of three contingent pressures, each now obsolete:

1. **The 09:10 truce** with a legacy force-graph renderer that no longer exists.
2. **The 11:30 garrison** kept after the war ended — a `MutationObserver`
   patrolling for an enemy that was already disarmed.
3. **The 23:40 debounce** that papered over an O(N) re-simulate the bridge's
   discourse made it impossible to replace with O(Δ).

None of these conditions hold today. The legacy renderer is gone. The phase
loader exists and could publish deltas. The tilemap pipeline already moved
layout authority to the server for >1M-node graphs (commit `dba2f16`,
2026-04-28) — proving the alternative is not only thinkable but *already
implemented in a sibling file*. The bridge's pattern persists by inertia of
discourse, not by necessity.

What appears as common-sense engineering ("destroy before remount, of course")
is the petrified residue of a 14-hour political settlement on 2026-04-22.

## Hand-offs

- **Constructive redesign of the bridge as long-lived service with `update(delta)` API** → Alexander (pattern language) + architect.
- **Empirical confirmation that incremental D3 update closes the freeze** → Galileo / Mill (measurement, A/B against current debounce).
- **Migration path: bridge subscribes to phase events instead of `state:lastData`, or delegates layout to tilemap entirely** → engineer; precedent already merged in `workflow_graph_tilemap.js`.
- **Document the genealogy in an ADR so the next session does not re-petrify the truce** → ADR author.

## Compliance check (coding-standards.md)

| Rule | Status | Note |
|---|---|---|
| §1.1 SRP | fail | Bridge does: detection, DOM eviction, MutationObserver patrol, debounce scheduling, render orchestration, view-switch reflow. Six reasons to change. |
| §2.2 Layer dependency | pass | Bridge sits in handlers/UI layer; does not violate inward arrows. |
| §6.1 Root-cause thinking | fail | The 23:40 debounce is a §6.1 textbook band-aid: fix at throw site (jank), not at classified cause (total re-render on append-shaped data). |
| §7.2 Local reasoning | fail | Three nested setTimeout closures + MutationObserver + module-scoped `_handle/_lastPayload/_pendingRender/_renderTimer/_firstRenderDone/_firstDeadline` — behavior is not predictable from the surrounding text. |
| §8 Sources | fail | Constants `400`, `500`, `5000`, `80`, `50`, `60` have no citation, no benchmark, no measurement record. Invented numbers. |
| §9 Anti-patterns | fail | "Catching errors just in case" (`try { _handle.destroy(); } catch (_) {}`) — three sites. Empty catches with no named failure mode. |
