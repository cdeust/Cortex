# Kauffman audit — layout authority at the edge of chaos

**Discipline:** Kauffman (1993, *Origins of Order*; 1995, *At Home in
the Universe*). Every coupling parameter K has an ordered regime
(K too low → frozen, no information flows, system is brittle to
bursts) and a chaotic regime (K too high → unbounded propagation,
GC pauses, latency tail explodes). The adaptive regime is the
narrow band between them. The audit's job is to locate that band
for each layout-authority parameter and produce **tunable setpoints
with diagnostic triggers**, not constants.

Setpoint format throughout: `(low, target, high)` plus the trigger
that should re-tune.

## 1. Phase diagram framework

- **Frozen (K → 0):** drops dominate / stride → ∞ / no buffer absorbs
  bursts. Information never reaches the client.
- **Adaptive (edge):** drops < 0.1 % at p99 burst; latency p99 bounded;
  memory headroom ≥ 2× sustained. The system absorbs new workloads.
- **Chaotic (K → ∞):** memory blowup, GC pauses, priority starvation,
  RTT tail explodes. Variance swamps the mean.

A setpoint is *adaptive* iff a 2× nominal burst keeps the system in
the adaptive band, not within 20 % of either edge.

## 2. Per-priority queue caps (`QUEUE_SIZES`, scheduler.py:78)

Source: `mcp_server/server/layout_authority_scheduler.py:78`. Service
rate μ = 7.28·10⁵ events/s (knuth.md integration bench).

| Priority | Frozen edge (K_low) | Adaptive setpoint (current) | Chaotic edge (K_high) | Re-tune trigger |
|---|---|---|---|---|
| P0 domain | < 50 (drops on any burst > 100 ms) | **1 000** | > 50 000 (≥ 4 MB just for P0) | drop_rate_P0 > 10⁻⁶ over 1 h |
| P1 tool_hub | < 50 | **1 000** | > 50 000 | drop_rate_P1 > 10⁻⁶ |
| P2 file | < 1 000 (seed_project bursts ~30 k files in < 1 s) | **16 000** | > 200 000 (3 MB / queue) | drop_rate_P2 > 10⁻³ during seed |
| P3 other | < 2 000 | **32 000** | > 400 000 | drop_rate_P3 > 10⁻³ |
| P4 symbol | < 4 000 | **64 000** | > 500 000 (40 MB → 8 MB ceiling breached, see scheduler.py:48) | drop_rate_P4 > 10⁻² (low-priority shedding *is* the design) |
| P5 edge | < 8 000 | **128 000** | > 1 000 000 (80 MB) | drop_rate_P5 > 10⁻¹ |
| P6 subtree | < 10 (coalescing fails) | **100** | > 1 000 (latency in viewport tracking) | viewport_lag > 200 ms |

**Edge-of-chaos rule:** cap_p ≈ 2× the largest known burst at priority
p, capped by the 8 MB working-set ceiling (cost-model.md §3) divided
by 80 B/item budget. Caps below 2× burst → frozen (everyone drops a
seed_project replay). Caps above 8 MB / 80 B = 100 k per priority for
P4–P5 → chaotic (memory blowup; matches scheduler.py:48 derivation).

## 3. Drain rate (worker pop loop, scheduler.py pop)

Drain rate δ_drain is implicit in μ_authority = 7.28·10⁵ events/s,
single core. The tunable is the **pop batch size** (currently 1 per
loop with strict-priority scan).

| Regime | Batch size | Behaviour |
|---|---|---|
| Frozen | 1 (current) under coarse lock | Lock-acquire dominates; observed μ is 728 k/s but P95 jitter elevated under contention |
| **Adaptive setpoint** | **8–32 items per pop** when next-item priority equals current | Amortises lock; matches observed cache-line block; preserves strict-priority by checking priority on each draw |
| Chaotic | > 256 | Higher priorities can starve for a full batch duration (~350 µs at P4) → P0 latency tail |

**Setpoint:** `BATCH_POP = (4, 16, 64)`. Trigger to re-tune: if
P0_to_render_p99 > 50 ms, reduce; if μ_authority_observed < 0.5·μ_max,
increase.

## 4. Replay buffer — `_EVENT_LOG_CAP` (log.py:42)

Current: `_EVENT_LOG_CAP = 500_000` events × ~200 B JSON ≈ **100 MB**
worst-case. Purpose: SSE reconnect replay window.

| Regime | Cap | Failure mode |
|---|---|---|
| Frozen | < 50 000 events (~10 s @ 5 k/s sustained) | Reconnects after a 30-s wifi blip miss state; client must full-resync (10⁶ nodes) |
| **Adaptive setpoint** | **(200 000, 500 000, 2 000 000)** | Covers a 60-s reconnect window at peak SSE drain (5·10⁴/s; erlang.md §2). Memory 40–400 MB — out of 8 MB working-set, but log lives in **renderer-side** layer, not authority core (cost-model.md §3) |
| Chaotic | > 5 000 000 | RAM pressure; Python deque resize stalls; GC pause > 100 ms |

**Re-tune trigger:** `reconnect_resync_rate > 1 %` of reconnects →
increase cap. `process_RSS > 1 GB` attributable to event log →
decrease cap.

## 5. Per-subscriber SSE queue (`_SUBSCRIBER_QUEUE_CAP`, log.py:43)

Current: 100 000. Erlang.md sets δ_sse ≈ 5·10⁴/s/client.

| Regime | Cap | Behaviour |
|---|---|---|
| Frozen | < 1 000 (< 20 ms drain headroom) | Any GC pause on the client → dead-queue eviction; erlang.md `_DEAD_QUEUE_MISS_THRESHOLD = 200` fires |
| **Adaptive setpoint** | **(20 000, 100 000, 400 000)** | 0.4 – 8 s of drain headroom; covers normal client jank without eviction |
| Chaotic | > 10⁶ | Per-client 200 MB; 10 clients → 2 GB; OOM |

**Re-tune trigger:** if dead_queue_evictions/h > 1 per healthy
client → raise floor. If SSE memory > 500 MB total → lower ceiling.

## 6. LOD stride (lod.py:58 `stride(zoom)`)

Current: `stride(zoom) = max(1, 2^(3 - 4·zoom))`. Range stride ∈ {1,2,4,8}.

This is the **coupling between zoom and visible-symbol count**.
- Stride = 1 always (frozen at chaotic edge): emit every symbol →
  10⁶ at zoom 0 → renderer chokes (see ginzburg.md visible-budget).
- Stride too aggressive (frozen at ordered edge): structure dissolves
  before user requests it. Visible drops to 10³ at zoom 0.5 → empty
  scene → user perceives data loss.

| Zoom | Frozen-low (K=∞, stride too big) | Adaptive setpoint | Chaotic-high (K=0, stride=1) |
|---|---|---|---|
| 1.00 | n/a | stride = **1** | n/a — full detail intended |
| 0.75 | 4 (lose mid-detail) | **(1, 1, 2)** | 1 in ultra-dense subtrees → > 50 k visible |
| 0.50 | 8 | **(2, 2, 4)** | 1 → > 250 k visible |
| 0.25 | 16 | **(4, 4, 8)** | 2 → > 250 k visible |
| 0.00 | 32 | **(8, 8, 16)** | 4 → > 100 k visible |

**Edge target:** visible_symbols(zoom) ∈ [10 000, 50 000] across the
range — Mandelbrot power law preserved (mandelbrot.md), Ginzburg
visible-budget honoured (ginzburg.md). Re-tune trigger: if
client_fps < 30 at any zoom for > 5 s → increase stride at that
zoom; if visible_symbols < 5 000 at zoom > 0.5 → decrease stride.

## 7. Pending-edges and per-file symbol caps (authority.py:48–49)

`_PENDING_EDGES_CAP = 100_000`, `_PENDING_SYMBOLS_CAP_PER_FILE = 4_096`.

| Param | Frozen | Adaptive (current) | Chaotic | Trigger |
|---|---|---|---|---|
| pending_edges | < 1 000 (drops during file-tree resolve burst) | **(20 000, 100 000, 500 000)** | > 5·10⁶ (memory blowup; resolve walk cost ~O(N) on flush) | edge_resolve_drop_rate > 10⁻² |
| symbols/file | < 64 (loses real files like 5 k-line generated code) | **(1 024, 4 096, 16 384)** | > 65 536 (per-file dict pathological) | symbol_drop_rate per file > 10⁻³ for files with documented size |

## 8. Far-reduced threshold (lod.py:52, `_FAR_ZOOM_THRESHOLD = 0.4`)

This is the **phase-transition coordinate** for memory/entity kinds.

- < 0.2 (frozen): memories visible at near-far zoom flood the scene.
- > 0.6 (chaotic at the structure side): memories disappear too soon;
  the user loses semantic anchor while still in mid-zoom.
- Adaptive band: **(0.3, 0.4, 0.5)**. Re-tune trigger: user studies
  / heatmaps showing > 30 % of zoom-time spent in [0.35, 0.45] without
  user-visible memory nodes → lower threshold.

## 9. Cross-coupling — the system K is itself a Kauffman variable

Each parameter above is one knob, but they interact. The composite
coupling K is:

```
K_system ≈ count_of_parameters_at_their_chaotic_edge_simultaneously
```

When K_system ≥ 2, regime collapse cascades (full P5 + 100 % stride =
1 at zoom 0 + full SSE queue → simultaneous OOM + drop + RTT tail).
**Operational rule:** never tune two parameters into their upper
quartile in the same release. Roll one, observe one full burst cycle,
then roll the next.

## 10. Setpoints summary (one-glance dashboard)

| Parameter | Low | **Target** | High | Owner trigger |
|---|---|---|---|---|
| QUEUE_SIZES[P2] | 4 000 | **16 000** | 64 000 | drop_rate_P2 > 10⁻³ |
| QUEUE_SIZES[P4] | 16 000 | **64 000** | 100 000 | working_set > 8 MB |
| QUEUE_SIZES[P5] | 32 000 | **128 000** | 200 000 | working_set > 8 MB |
| BATCH_POP | 4 | **16** | 64 | P0_p99 > 50 ms |
| EVENT_LOG_CAP | 200 k | **500 k** | 2 M | reconnect_resync > 1 % |
| SUBSCRIBER_QUEUE_CAP | 20 k | **100 k** | 400 k | dead_queue_eviction > 1/h/client |
| FAR_ZOOM_THRESHOLD | 0.30 | **0.40** | 0.50 | user dwell > 30 % in dead band |
| pending_edges | 20 k | **100 k** | 500 k | edge_resolve_drop > 10⁻² |
| symbols/file | 1 024 | **4 096** | 16 384 | per-file_symbol_drop > 10⁻³ |
| stride(z=0) | 4 | **8** | 16 | visible@z0 ∉ [10 k, 50 k] |

## 11. Anti-patterns refused

- Static constants without a re-tune trigger and observability counter
  — frozen by construction.
- Tuning everything to "max" (chaotic) or "min" (frozen).
- Single-knob optimisation against one benchmark — ignores K_system (§9).

## 12. Hand-offs

- Capacity math at these setpoints → **erlang.md**.
- Power-law stride continuity → **mandelbrot.md**.
- Working-set ceiling bounding the chaotic edge → **cost-model.md §3**.
- Visible-symbol budget bounding stride → **ginzburg.md**.
- Telemetry driving the re-tune triggers → **deming.md** (control charts).
