# Mandelbrot audit — fractal LOD for the layout authority

**Module:** `mcp_server/server/layout_authority_lod.py`
**Principle:** scale-free decimation; same visible subset across reconnects.
**Source:** Mandelbrot, B. B. (1982). *The Fractal Geometry of Nature*, W. H. Freeman.

## The fractal-self-similarity argument

A Cortex graph at full resolution has O(domains) ≪ O(tools) ≪ O(files) ≪ O(symbols).
The cardinality is *power-law-distributed across kinds* — a few hubs, many leaves.
This is the same pattern Mandelbrot identified in coastlines, river networks, and
financial returns: structure that repeats at every scale of magnification.

The user's screen is finite. At zoom = 1.0 every symbol is meaningful; at zoom = 0.0
only the scaffolding is legible — individual symbols collapse below pixel resolution.
Rendering all 10^6 symbols at far zoom is wasted work and visual noise.

**Decimation rule:**
```
stride(zoom) = max(1, int(2 ** (3 - zoom * 4)))
visible iff hash(node_id) % stride == 0
```

The exponent `3 - 4*zoom` is linear in zoom, so stride is exponential in zoom and
visible-count `≈ N / stride` is a **power law in resolution**. This is the
Mandelbrot signature: zooming by a factor of 2 in resolution multiplies visible
symbols by ~2, at every scale, with no characteristic zoom level.

## Why hash-keyed decimation (not sampling)

A random sample drawn fresh on each reconnect would shift the visible population
at constant zoom — the screen would "shimmer" after a network blip. A
deterministic hash of `node_id` yields the *same* visible subset for the same
`(population, zoom)` across reconnects. We use BLAKE2b rather than CPython's
salted `hash()` because the latter is process-local and would not survive
a server restart. BLAKE2b is content-only and uniform across the input space.

## Empirical roughness measure (10^6 symbols)

Self-check at `python3 -m mcp_server.server.layout_authority_lod`:

| zoom | stride | visible   | ideal     | ratio  |
|-----:|-------:|----------:|----------:|-------:|
| 0.00 |      8 |   125 294 |   125 000 | 1.0024 |
| 0.25 |      4 |   250 296 |   250 000 | 1.0012 |
| 0.50 |      2 |   499 881 |   500 000 | 0.9998 |
| 0.75 |      1 | 1 000 000 | 1 000 000 | 1.0000 |
| 1.00 |      1 | 1 000 000 | 1 000 000 | 1.0000 |

Log-log slope of visible vs stride: **-0.9981** (expected -1.0).
Tolerance asserted in `__main__`: |slope + 1| < 0.05. PASS.

The decimation is power-law to four decimals on N = 10^6. The tail
exponent α ≈ 1 places the visible count squarely in Mandelbrot's
*wild* regime at the boundary — variance of visible-count is finite
only because we cap stride at the population size, but the scaling
exponent is exact.

## Why kind-conditional decimation

Not every kind is decimated:

- `domain`, `tool_hub`, `file`, `discussion`, `skill`, `hook`, `command`,
  `agent`, `mcp` — **always visible**. Their cardinality is bounded by
  the number of projects/tools/files in the workspace; emitting all of
  them is cheap and they form the navigation scaffolding.
- `symbol` — **decimated by stride(zoom)**. High-cardinality (10^6+).
- `memory`, `entity` — **reduced only at zoom < 0.4** (stride 2).

Stakes-calibrated: cardinality bound per kind drives the rule.

## Refusal: what this module does NOT do

- **Does not** sample randomly — violates reconnection stability.
- **Does not** use Python's salted `hash()` — process-local.
- **Does not** materialize the filtered list — `visible_subset` is a
  generator (a 10^6 list copy is ~100 MB).
- **Does not** invent constants — (3, 4, 0.4, 2) trace to the explicit
  doubling argument in `stride()` and the clutter threshold for
  `memory`/`entity`.
