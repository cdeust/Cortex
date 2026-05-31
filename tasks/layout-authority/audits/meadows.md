# Meadows — Leverage-Point Analysis of the Layout Authority

> Where on the 12-point hierarchy does each module sit, and which is the
> highest-leverage intervention currently unused? Ginzburg flagged the
> paradigm: "the renderer is responsible for placing nodes." Meadows
> ranks paradigm change at #2 — second only to transcending paradigms.

## 1. System map (stocks / flows / delays)

| Stock | Inflow | Outflow | Delay |
|---|---|---|---|
| `(node_id) → (x, y)` mapping (5 disjoint copies) | builder appends, renderer simulates, igraph DrL pass, tilemap rasterizer, JS `prepareTopology` | nothing — every layer writes, none deletes | seconds–minutes (DrL = 90 s/1M; debounce = 1.2 s; SSE = unbounded) |
| Pending edges / pending symbols | builder emits before parent | flush on parent arrival | seconds (depends on stream order) |
| Renderer simulation state | per-phase rebuild | MutationObserver eviction | 1.2 s debounce + async re-mount |
| Topology fingerprint cache | recompute_layout writes | TTL expiry | undefined (skip-if-fresh patch) |

Five writers, zero contracted owner, no expiry policy. The stock has no conservation law.

## 2. Feedback loops

| Loop | Type | Mechanism | Dominant? |
|---|---|---|---|
| L1: phase append → renderer destroys & rebuilds simulation → freezes → debounce raised | reinforcing (vicious) | bridge.js:107–137 | yes, at >10k nodes |
| L2: MutationObserver evicts legacy DOM ↔ force-graph re-mounts | reinforcing | bridge.js:67–73 | yes |
| L3: tilemap 503 `no_layout` → client calls `/api/recompute_layout` → retries `/api/quadtree` | balancing (self-healing) | tilemap.js:122–168 + quadtree_handler.py:33–40 | yes when cold-start |
| L4: skip-if-fresh cache balances three callers of `recompute_layout` | balancing | recompute_layout.py:82–99 | yes, papering over L3 |
| L5: counter bump → `compute_slot` → wire emit → SSE drain (proposed authority) | balancing, monotone | layout_authority.py | NOT YET DOMINANT |

L1+L2 dominate today. The proposed L5 is the only loop with O(1) per-node insertion and a single producer. **Loop dominance must shift from L1 to L5.**

## 3. Module → leverage point mapping

| Module | Leverage level | Why |
|---|---|---|
| `mcp_server/server/layout_authority_geometry.py` constants (`SETUP_R=70`, `TOOL_R=140`, `phi=π(3-√5)`) | **#12 — constants** | Numbers tuned for visual quality. Tweaking them does not change behavior. |
| `_PENDING_EDGES_CAP=100_000`, `_PENDING_SYMBOLS_CAP_PER_FILE=4_096` (layout_authority.py:48-49) | **#11 — buffer sizes** | Bigger ≠ better; a buffer is a symptom of unaligned producer/consumer rates. |
| `layout_pg_store.py`, tilemap Arrow buffer, plugin module snapshot, HTTP graph cache (visualize_bootstrap.py:56-104) | **#10 — stock-flow structure** | Three caches, three lifetimes, no coordination. Restructuring caches is medium leverage. |
| Debounce 1.2 s in `workflow_graph_bridge.js:107-137`; DrL 90 s pass in `recompute_layout.py`; SSE drain timing | **#9 — delays** | Where intuition fails. Each iteration tuned the delay, none removed it. |
| MutationObserver (bridge.js:67-73), skip-if-fresh cache (recompute_layout.py:82-99), tilemap retry (tilemap.js:122-168) | **#8 — balancing loops** | All three are referees added because authority is unclear. Adding more balancing loops cannot fix the underlying paradigm. |
| `prepareTopology` per-phase rebuild + per-event SSE recompute (bridge.js, polling.js) | **#7 — reinforcing loops** | Vicious cycle: more nodes → longer rebuild → larger debounce → staler view. |
| Two parallel pipelines fighting on `lastData` (polling.js:30-37); 503 `no_layout` signaling (quadtree_handler.py:33-40); `/api/recompute_layout` callable from 3 sites | **#6 — information flows** | Layers signal to each other through error codes and shared mutable state, not contracts. High leverage if cleaned. |
| cost-model.md §6 "no per-frame iteration over siblings"; alkhwarizmi `compute_slot` O(1) contract; dijkstra H1/H2 (single producer, monotonic seq) | **#5 — rules** | The constraints are written but not enforced — `core/layout_engine.py` (DrL, O(N log N)) violates §6 yet still ships. |
| `core/layout_engine.py` (igraph DrL); proposed `mcp_server/server/layout_authority*.py` (8 modules); `ui/unified/js/workflow_graph.js:308-700` `prepareTopology`/`computeSlots` | **#4 — self-organization** | Three independent layout systems self-organized into one codebase. Removing two of them is a structural intervention. |
| `recompute_layout.py` exists; `quadtree_handler.py` 503-and-recover; `layout_authority` modules built but not yet single-producer | **#3 — goals** | Implicit goal today: "let any layer that wants to compute layout do so." Should be: "exactly one module owns `(node_id) → (x, y)`." |
| **"The renderer is responsible for placing nodes"** (Ginzburg §4) | **#2 — paradigm** | The single load-bearing assumption that survives every rewrite. Six algorithms, six symptoms cured, one paradigm preserved. |
| Ability to step outside "renderer vs server" framing entirely | **#1 — transcendence** | Possible reframe: layout is not "computed by someone" — it is a *property of the node* assigned at insertion time, served as a read-only stream. The question "who computes?" dissolves. |

## 4. Archetype diagnosis

**Pattern matched: Shifting the Burden** (Meadows 2008, Ch. 5).

- *Symptom:* renderer is too slow / freezes / clumps.
- *Quick fix that worked short-term:* move layout one layer up (raster tiles, SSE rebuild, server DrL, tilemap auto-recompute).
- *Fundamental solution that atrophies:* **invert authority** — make the server the sole producer of `(x, y)`.
- *Side effect:* each quick fix adds a new layer that *also* claims layout authority, *worsening* the underlying ambiguity. Five copies of the stock now exist.

Secondary archetype: **Fixes that Fail.** Each fix introduced a new feedback loop (debounce, MutationObserver, skip-if-fresh, tilemap retry) that re-created the original symptom in a new form.

Known intervention for Shifting the Burden: **strengthen the fundamental solution; remove the addictive quick-fix capacity.** Concretely: (a) make the authority real, (b) *delete* the alternatives so they cannot be reached for again.

## 5. Highest unused leverage points

Ranked by leverage × feasibility:

| Rank | Leverage | Intervention | Feasibility | Time-to-effect |
|---|---|---|---|---|
| **A** | **#2 paradigm** | Declare: *the renderer never computes layout; it consumes `(id, x, y, seq)` from one stream.* Land it in `tasks/layout-authority/` as a binding contract. | Low cost, high political. Already drafted in cost-model.md §7 + ginzburg §5. | Immediate (decision); weeks (compliance) |
| **B** | **#4 self-organization (delete)** | Delete `core/layout_engine.py` (DrL, violates rule #5 cost-model §6). Delete `prepareTopology`+`computeSlots` (workflow_graph.js:308-700). Delete `recompute_layout.py` skip-if-fresh patch. | Mechanical refactor, ~400 LOC removed | days |
| C | #5 rules | Add CI check: any new function returning `(x, y)` outside `mcp_server/server/layout_authority*` fails build. | Low cost | days |
| D | #6 info flows | Replace 503-`no_layout` signaling with a single SSE topic; remove client-triggered `/api/recompute_layout`. | Medium cost | week |
| E | #8 balancing loops removal | Once A+B land, MutationObserver, skip-if-fresh, debounce 1.2s become inert and can be deleted. | Trivial after B | hour |

**Do not start at C, D, or E.** Without A and B, the paradigm reasserts itself: the next contributor will add the seventh layout system because the precedent of five permits it.

## 6. Recommendation — the one or two interventions

### Intervention 1 (paradigm, #2) — **mandatory, week 0**
Ratify a one-page contract in this folder: *"Layout authority owns `(node_id) → (x, y)`. Renderers are read-only consumers of an append-only, monotonically-versioned stream. No other module may produce coordinates."* Cite alkhwarizmi.md `add_node` + dijkstra.md H1/H2 as the formal invariants. This is cheap to write and expensive to ignore — once it exists, every PR is measured against it.

### Intervention 2 (self-organization removal, #4) — **mandatory, week 1**
Delete the alternatives in one PR:
1. `mcp_server/core/layout_engine.py` — entire file.
2. `ui/unified/js/workflow_graph.js:308–700` — `prepareTopology` + `computeSlots`.
3. `mcp_server/handlers/recompute_layout.py` — skip-if-fresh path; collapse to a single `bootstrap_authority()` call.
4. `ui/unified/js/workflow_graph_tilemap.js:122–168` — client-triggered recompute branch.
5. `ui/unified/js/workflow_graph_bridge.js:67–73` — MutationObserver (now only one renderer remains).

Net: **~600 LOC removed**, three caches collapse to one, MutationObserver becomes provably unnecessary.

## 7. Predicted system response (with delays)

- **t = 0** (paradigm + deletes land): build-and-test breaks loudly because L1 and L2 no longer exist; renderer cannot freeze because there is nothing to rebuild.
- **t = 1 day:** authority becomes the only path; tilemap subscribes to the one SSE stream.
- **t = 1 week:** dominance shifts from L1 (vicious) to L5 (balancing). User-visible: smoother stream, no debounce stutter, deterministic placement of node #10⁹.
- **Risk of overshoot:** none — the closed-form O(1) compute_slot has no oscillation modes (no integral term, no damping coefficient).
- **Risk of regression:** if anyone re-introduces a layer that produces `(x, y)`, the paradigm has not been internalized — escalate to rule #5 enforcement (CI lint).

## 8. Refusal conditions hit / not hit

- ✅ System map present (§1).
- ✅ Feedback loops identified (§2).
- ✅ Delays mapped (§1, §2).
- ✅ Archetype validated against actual structure (§4 — five-stock evidence from Ginzburg §3).
- ✅ Leverage rank named for each intervention (§3, §5).
- ✅ Feasibility + time-to-effect estimated (§5, §7).
- Not applicable: this is not a 2-variable problem; systems thinking justified.

## 9. Hand-offs

- **Ginzburg** — already named the paradigm (§4 of his audit). Meadows confirms it is leverage point #2 and adds: paradigms die only when the alternatives are deleted, not merely deprecated.
- **Alkhwarizmi** — owns the `add_node` / `compute_slot` contract that becomes the new paradigm's formal expression.
- **Dijkstra** — owns H1 (single producer) / H2 (monotonic seq) — these are the rules (#5) that operationalize the paradigm.
- **Beer** — once authority is single, VSM viability of the layout subsystem becomes assessable; until then it is structurally non-viable.
- **Curie** — measure pre/post: count of `(x, y)` writers in the codebase (target: 1), debounce duration (target: 0), MutationObserver invocations (target: 0).
- **Engineer** — execute Intervention 2 (the deletion PR) once Intervention 1 is ratified.

## 10. The single sentence

> The leverage is not in choosing a better layout algorithm. It is in
> choosing **who** is allowed to author one — and deleting everyone else.
