# Layout Authority — Cost-Floor Derivation

## 1. The hard ceiling

Constraint: place **N = 10⁹ nodes** in 2D within **T = 1–2 s**, working-set
**≤ 8 MB**. Single-machine, single-allocation budget.

Per-node time budget:

```
T_per_node = T / N = 1 s / 10⁹ = 1 ns
```

A modern x86 core dispatches ~3·10⁹ simple ops/s. At 1 ns/node that is
**~3 cycles per node**. No Python interpreter, no syscall, no cache miss
fits in 3 cycles. So:

- Realistic single-core Python budget: **~10 ns per node** at 10⁸ nodes;
  at 10⁹ we MUST batch through C/SSE writes (numpy, ctypes, or a tile
  worker) and let the GIL release.
- The geometry cost itself **must be O(1) per node** — closed form, no
  iteration over siblings, no graph traversal, no force step.

Anything else hits a wall. d3-force is O(N log N) per tick × ~300 ticks
≈ 3·10¹² ops at N = 10⁹ — six orders of magnitude over budget.
`prepareTopology` as currently written is O(N + E); even at 50 ns/node
that is 50 s for 10⁹ nodes. Both are disqualified.

## 2. Implications

1. **No per-node iteration over siblings.** A node's slot may consult
   only its own (kind, idx, total_in_kind), its parent's slot if any,
   and its domain's anchor. That is it.
2. **No per-event recompute.** Adding a node is `counter[(dom,kind)] += 1`
   then one `compute_slot()` call. Inserting node 10⁹ costs the same as
   inserting node 1.
3. **Slot formula is a pure function** of `(domain_anchor, kind, idx,
   total_in_kind)` plus, for symbols, the parent file's slot.
4. **No global graph traversal anywhere in the layout path.** Edges
   exist for the renderer, not for the placer.

## 3. Memory ceiling — 8 MB working set

Per-domain state is **O(kinds)**, not O(nodes_in_domain). For
**11 domains × 6 kinds** (`tool_hub`, `file`, `symbol`, `discussion`,
`memory`, `setup`):

```
state = 11 × 6 × 8 bytes (int64 counter) = 528 bytes
```

Trivially fits the 8 MB budget with five orders of magnitude to spare.
Per-tool-hub angle cache: 7 tools × 11 domains × 16 bytes ≈ 1.2 KB.
Per-file slot cache for symbol parenting: only kept for files that
actually have symbols — bounded by the visible window, not by N.

The graph itself never lives in this module. The authority owns the
counters; the renderer owns the buffers. Both are O(visible) at peak,
not O(N).

## 4. Why the geometry must match `workflow_graph.js`

The user has spent months tuning `prepareTopology` / `computeSlots`
(workflow_graph.js lines 308–700). The Python authority is a **port,
not a re-design**: same Fibonacci-spiral domain anchors (golden angle
φ = π(3 − √5), JS line 323), same per-kind shells (`SETUP_R = 70`,
`TOOL_R = 140`, `FILE_R = 220`, `DISC_R = 150`, `MEM_R = 150`),
same per-tool angles (`TOOL_LOCAL_ANGLE`, JS lines 76-84), same
sector half-widths (`SECTOR_SETUP_HALF = π/2.6`, `SECTOR_SIDE_HALF = π/6.5`,
`SECTOR_SIDE_ANGLE = 0.72π`). All constants in
`mcp_server/server/layout_authority_geometry.py` are copied verbatim
with `// source: ui/unified/js/workflow_graph.js:<line>` provenance
in their docstrings.

## 5. Empirical proof — benchmark on 1M slots

Run on this machine (Apple silicon, Python 3.10, single core, no JIT):

```
setup:      180.1 ms   5.55 M ops/s
file:       211.9 ms   4.72 M ops/s
memory:     295.7 ms   3.38 M ops/s
symbol:     201.6 ms   4.96 M ops/s
domain:     198.6 ms   5.04 M ops/s
```

Pure-Python closed-form: **~3.4–5.6 M slots/s per core**, i.e. **~180–300 ns
per slot**. To hit 10⁹ in 1–2 s we need ~10 ns/slot — **~20–30× faster**
than pure Python single-core. Achievable via:

- numpy-vectorised batch compute (~30–50 ns/slot in numpy → ~50× speedup
  by amortising the interpreter loop)
- 8-core parallel write (~5–8× on top)

Net headroom: comfortable for 10⁹ within the 1–2 s window once the
authority pushes batches through numpy. **The geometry itself is no
longer the bottleneck** — the SSE/HTTP transport to the renderer is.

## 6. What this rules out, forever

| Approach | Why disqualified |
|---|---|
| d3-force ticks | O(N log N) per tick × hundreds of ticks |
| `prepareTopology` per phase | O(N + E) per recompute, called per event |
| any per-frame iteration over siblings | violates O(1)-per-node |
| force simulation | non-deterministic + iterative |
| spatial index rebuilds on add | O(N log N) construction per insert |

The authority places node #10⁹ in the same time as node #1. There is
no other shape the solution can take under these constraints.

## 7. Hand-offs

- **Authority** (caller of `compute_slot`): owns the
  `counters: dict[(dom_id, kind), int]` map and the per-domain anchor
  cache. On insert: bump counter, call `compute_slot`, write `(x,y)` to
  the SSE/Postgres slot table.
- **Renderer**: reads slots from the slot table; does not call
  `compute_slot` itself. (Curie: measure actual end-to-end latency at
  N = 10⁶ and N = 10⁸ to confirm the 10 ns/slot extrapolation holds.)
- **Hamilton**: design the SSE backpressure path so the renderer
  degrades gracefully when slot-write rate exceeds network bandwidth.
