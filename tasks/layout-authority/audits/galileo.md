# Galileo audit — idealization of the Cortex layout authority

Strip every secondary effect (network jitter, GIL, browser GC, SSE proxy buffering, syscalls, interpreter dispatch, allocator) and ask: what is the **fundamental law** the system would obey if all friction vanished? Then check what the current design fights vs accepts.

## 1. Phenomenon

Place N nodes (target N = 10⁹) in 2D for a Cortex graph viewport, working‑set ≤ 8 MB, end‑to‑end build/stream ≤ 1–2 s. The "8 MB IoT" framing is: can the layout authority be reduced to a constant‑memory, constant‑time‑per‑node oracle that runs at the speed of its own arithmetic?

## 2. Variable decomposition (essential vs friction)

| Variable | Essential? | Rationale |
|---|---|---|
| `domain_index → anchor` (Fibonacci spiral) | **Essential** | The phenomenon IS positional placement. Without this map there is no layout. |
| `kind` (domain/tool_hub/file/symbol/discussion/memory/mcp) | **Essential** | Selects which closed‑form helper applies; cannot be removed without erasing the visual grammar. |
| `idx_in_kind`, `total_in_kind` | **Essential** | Sole inputs needed to deterministically distribute siblings within a kind's sector/ring. |
| `parent_slot` (symbol→file petal) | **Essential** | The only allowed "graph" lookup — bounded depth 1, O(1). Carries the parent‑child binding that makes symbol clouds readable. |
| Fixed radii / sector half‑widths (SETUP_R, TOOL_R, FILE_R, SECTOR_*) | **Essential** | Shell separation invariants — without them shells fuse. Copy‑verbatim from `workflow_graph.js`. |
| Network jitter / SSE proxy buffering | Friction | Transport, not geometry. Slot is correct independent of when it arrives. |
| GIL contention, Python interpreter overhead | Friction | Each slot is mathematically defined; interpreter merely realizes it slowly. |
| Browser GC pauses, render frame timing | Friction | Renderer cadence does not change `(x,y)`. |
| OS context switches, syscall cost | Friction | Same. |
| Edge list, full graph topology | Friction (for the placer) | Edges are renderer concerns. Slot does not depend on E. |
| Force‑step iteration count (d3‑force, DrL) | Friction (and disqualifying) | The fundamental law has no time dimension; iteration is an admission that the placer doesn't know the answer in closed form. |
| Spatial index (quadtree) for *placement* | Friction | Quadtree is a *retrieval/render* index, not a placement input. |
| Per‑event recompute of all siblings | Friction | A symptom of state coupling that the closed‑form law denies. |
| `prepareTopology` O(N+E) pre‑pass | Friction | Entire pass disappears if `(idx_in_kind, total_in_kind)` are tracked by the producer's counter dict. |

## 3. The idealized system (frictionless law)

```
slot : (domain_index, kind, idx_in_kind, total_in_kind, parent_slot?) → (x, y)
```

Properties of the idealized law:

1. **Pure function.** No hidden state, no mutation, no time. Same inputs → same `(x,y)` forever.
2. **O(1) per node.** No iteration over siblings, no global pass, no graph traversal beyond the single optional parent dereference (depth 1).
3. **State is O(domains × kinds), not O(N).** ~528 B counter table. The "8 MB IoT" budget is met with five orders of magnitude to spare.
4. **Insertion of node #10⁹ costs the same as node #1.** The fundamental law is acceleration‑free in N: distance from idle to placed is independent of crowd size, exactly as Galileo's idealized fall is independent of mass.
5. **Edges do not enter the placer.** The placer's domain is geometry; the edge list is the renderer's concern.

This already exists, almost cleanly, in `mcp_server/server/layout_authority_geometry.py` (218 lines, all closed‑form, all `O(1)` branches, no loops over N). That file IS the idealized Galilean law. Everything else in `layout_authority_*` is friction management.

## 4. The inclined plane (slow‑down to observe)

10⁹ nodes is too fast to inspect. Run the same closed‑form law at N = 10⁶ on one core (current `bench_layout_authority.py`) and the dynamics are preserved exactly — only the rate scales:

```
Measured: 3.4–5.6 M slots/s/core   (180–300 ns/slot, pure Python)
Required: ~10 ns/slot               (1 ns × ~10× headroom)
Gap: ~20–30× — closes via numpy‑vectorised batch + multi‑core fan‑out
```

The geometry itself (the law) is no longer the bottleneck. The inclined plane confirms it; the rest is transport.

## 5. Quantitative measurements (not impressions)

| Qualitative claim | Measurement | Value |
|---|---|---|
| "Closed form is fast enough" | bench_layout_authority.py | 3.4–5.6 M slots/s/core |
| "State is small" | 11 dom × 6 kinds × 8 B counter | 528 B |
| "Event log is bounded" | `_EVENT_LOG_CAP × ~112 B` | ≈ 56 MB (Fermi) — **busts 8 MB** |
| "Subscriber queues are bounded" | `_SUBSCRIBER_QUEUE_CAP × 112 B` | ≈ 11 MB per slow client — **busts 8 MB** |
| "Scheduler queues fit budget" | sum of `QUEUE_SIZES` × 80 B | ≈ 19 MB — **busts 8 MB** |
| "10⁹ nodes in 1–2 s end‑to‑end" | Fermi bracket via SSE + render | 10⁴–10⁵ s ≈ 3–30 h (×4 with edges) |

The geometry meets the IoT 8 MB budget. **The transport stack does not.** The law is frictionless; the channel that carries it is where the actual mass sits.

## 6. Authority vs observation

| Authority claim | Direct observation | Verdict |
|---|---|---|
| "The authority is a pure function `(dom,kind,idx,total,parent?)→(x,y)`" | `layout_authority_geometry.py` is exactly this | **Confirmed.** |
| "Working set ≤ 8 MB" (cost‑model.md §3) | log + scheduler + subscriber queues sum to tens of MB (Fermi audit) | **Refuted at the system level.** Geometry meets it; surrounding infrastructure does not. |
| "Authority places node #10⁹ in same time as node #1" | True for the geometry; false for the pipeline (event‑log replay, SSE backpressure, browser apply‑rate are all O(N)‑ish in wall time) | **Partially true.** The law is friction‑free; the realization is not. |
| "We can stream 10⁹ in 1–2 s" | Fermi bracket: 10–100 hours including edges | **Refuted.** Build is offline + tile‑served, not live‑streamed. |

## 7. Friction sources the design currently fights vs accepts

**Accepts (correctly — the law remains intact):**
- Closed‑form per‑kind helpers, no iteration. ✓
- O(domains × kinds) counter state. ✓
- No edges in the placer. ✓
- Symbol parent dereference is depth‑1, O(1). ✓
- Domain anchors via Fibonacci spiral derived from `index` alone. ✓

**Fights (friction the design tries to absorb rather than remove):**
- **Event log of 500k entries (~56 MB).** Friction: tries to support late subscribers via replay. Removal: snapshot‑on‑connect + tail‑forward, drop the unbounded log. The fundamental law is replayable from `(domain_index, kind, idx, total)` alone — the log stores derived data.
- **Per‑subscriber 100k queue (~11 MB each).** Friction: tolerates slow clients. Removal: snapshot + drop‑oldest, since `(x,y)` for a given `(dom,kind,idx)` is *idempotent and recomputable* — there is no value in retaining an old delta if the client can re‑derive.
- **Scheduler with 7 priority queues totalling ~19 MB.** Friction: smooths bursty producers. Under the idealized law a burst of N inserts is N counter bumps + N closed‑form calls; the scheduler exists because the *rest* of the pipeline (SSE, browser) cannot keep up. The scheduler is not solving a layout problem; it is solving a transport problem. It belongs to the renderer, not the authority.
- **`recompute_layout` 90 s synchronous DrL pass.** Direct refutation of the fundamental law. DrL is iterative force simulation — exactly the disqualified family in cost‑model.md §6. Its presence in the handler means the closed‑form authority is not yet the sole placement path; an iterative competitor still runs.
- **`prepareTopology` (JS side) O(N+E) pre‑pass.** Friction: pre‑computes `(idx, total)` by walking the graph. Removal: producer maintains `counter[(dom,kind)]` and emits `idx_in_kind` inline; the JS pre‑pass disappears.

## 8. The "8 MB IoT" question, answered Galilean‑style

**Yes** — the *layout authority* (the law) already runs in 528 bytes of state and O(1) per node. It is friction‑free at the IoT budget.

**No** — the *system around it* does not, because it carries three accreted layers of transport friction (event log, per‑client queues, priority scheduler) whose combined working set is 60–80 MB. These layers exist because the renderer cannot ingest at the producer's rate; they are not part of the law.

To run the *system* at the law's speed:

1. **Delete the event log.** Replace with snapshot‑on‑connect (re‑emit slots from counters in domain order — same closed form). Saves ~56 MB. Subscriber late‑join becomes O(visible), not O(history).
2. **Bound subscriber queues to 1 frame (~10³ events).** Drop‑oldest on overflow; clients re‑sync via snapshot. Saves ~11 MB per client.
3. **Move the scheduler out of the authority.** It is a *renderer adapter* concern. The authority emits at law‑rate; the adapter throttles to channel‑rate.
4. **Remove `recompute_layout`'s DrL path.** The iterative competitor must go; closed‑form is the only placer.
5. **Remove `prepareTopology`'s O(N+E) walk.** Producer emits `(idx_in_kind, total_in_kind)` directly from its counter; consumer trusts it.

After these five removals the system's working‑set drops from ~80 MB to ~1 MB and per‑node cost drops from "transport‑bound at 10⁴ evt/s" to "law‑bound at 10⁶+ evt/s". The 8 MB IoT shape becomes feasible — not as an aspiration, but as a consequence of removing what isn't load‑bearing.

## 9. Corrections to add (after the law is established)

| Secondary effect | When to add back |
|---|---|
| Backpressure for genuinely slow consumers | After snapshot path proves correct end‑to‑end. |
| Multi‑producer (currently single‑producer invariant) | Only when a benchmarked need exists; today single‑producer + closed‑form is sufficient. |
| Tile/Datashader path for visual aggregation | Already correct: it operates on slots, not on the law. Keep. |
| Numpy vectorisation of `compute_slot` | Add when single‑core 5 M slots/s becomes the bottleneck (today it isn't — transport is). |

## 10. Hand‑offs

- **Curie** — measure browser apply‑rate at 10⁵, 10⁶, 10⁷ to refine the 10⁴–10⁵ evt/s bracket; isolates the binding constraint.
- **Noether** — formalize the symmetry: the law is invariant under any permutation of `idx_in_kind` that preserves `(idx, total)`, and under any pure rotation of the domain anchor frame. These symmetries justify dropping the event log.
- **Feynman** — integrity audit on whether `recompute_layout`'s DrL pass is still wired into any path that bypasses the closed‑form authority; if so, that's a layer violation of the law.

## 11. Refusal note

The cost‑model document claims the system meets 8 MB. The geometry does; the surrounding transport stack (log + queues + scheduler ≈ 80 MB) does not. Per refusal condition #1 (idealizing away the variable that carries the phenomenon), the transport friction is **not** the phenomenon — the phenomenon is placement — and may be removed. Per refusal condition #2 (qualitative claim), the 8 MB claim must be measured at the *whole system* level, not just at the geometry module, before being treated as established.

---

**Files referenced (absolute):**
- `/Users/cdeust/Developments/Cortex/mcp_server/server/layout_authority_geometry.py` — the law (218 lines, closed‑form)
- `/Users/cdeust/Developments/Cortex/mcp_server/server/layout_authority_log.py` — friction layer 1 (event log)
- `/Users/cdeust/Developments/Cortex/mcp_server/server/layout_authority_scheduler.py` — friction layer 2 (priority queues)
- `/Users/cdeust/Developments/Cortex/mcp_server/server/layout_authority_protocol.py` — friction layer 3 (subscriber queues)
- `/Users/cdeust/Developments/Cortex/mcp_server/handlers/recompute_layout.py` — iterative competitor still wired
- `/Users/cdeust/Developments/Cortex/tasks/layout-authority/cost-model.md` — derivation
- `/Users/cdeust/Developments/Cortex/tasks/layout-authority/audits/fermi.md` — bracket cross‑check
