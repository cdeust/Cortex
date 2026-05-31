# Archimedes audit — `layout_authority_geometry.py`

Two-stage. Discovery by physical/mechanical analogy; proof by independent
interval arithmetic on the source. They share no assumptions beyond
`|cos|,|sin| ≤ 1`.

## Stage 1 — Heuristic (mechanical analogy)

Each domain is a small solar system anchored at a Fibonacci-spiral position.
Around each anchor, kinds occupy nested shells: MCP (50), setup (70), tool
hubs (140), disc/mem lanes (150) on opposite sides, files (220), symbols as
petals around each file. Every node's `(x,y)` is a *pure function* of
`(domain_index, kind, idx_in_bucket, total_in_bucket)` — no neighbours,
no forces, no iteration. The layout is the equilibrium of an already-
decoupled system; same inputs → same position, regardless of N.

Constants (`SETUP_R=70`, `TOOL_R=140`, `FILE_R=220`, sector half-widths,
`TOOL_LOCAL_ANGLE`, golden angle `_PHI`) are **copied verbatim from
`workflow_graph.js` lines 43–84, 313–541**. The Python authority re-projects
the same closed form into the server tier; the visual invariants the user
already approves (radial outward axis, petals around hubs, MCPs inward) are
preserved by construction.

O(1) per node holds: each helper does a fixed number of trig ops; state is
`O(domains × kinds)` integer counters (~528 B for 11×6).

Heuristic candidate: **within a domain, different-kind slots cannot collide
because each kind owns a distinct radius shell — except DISC/MEM which share
`r≈150` and rely on disjoint angular sectors.**

---

## Stage 2 — Proof sketch (independent: pure interval bounds)

Fix one domain anchor `A=(ax,ay)`, outward axis `ω`. For any kind `k`, the
emitted slot has the form `A + r_k · (cos θ_k, sin θ_k)` with explicit
intervals for `r_k` and `θ_k` derived directly from the source.

### Boundedness & finiteness

For every helper, `r` is `R_kind + small_offset(idx % m)` with `m∈{2,3,4}`
and offsets ≤ 8 px. `cos`/`sin` are bounded in `[-1,1]`. Therefore
`|x-ax|, |y-ay| ≤ r_max < ∞`. The dispatcher's fallback returns the anchor
itself, never NaN. `base_radius` takes `max(...)` over two finite positives,
so the domain shell is finite for any `n_domains ≥ 0` (the `max(n,1)` guard
prevents division by zero in `domain_anchor`, `slot_for_*`). All slot
coordinates are therefore finite real numbers. ∎

### Per-kind radius intervals (read off the source)

| kind        | r interval (px)              | source                   |
|-------------|------------------------------|--------------------------|
| mcp         | exactly 50                   | line 165                 |
| setup       | [70, 78]   (`idx%2 · 8`)     | line 102                 |
| tool_hub    | exactly 140                  | line 112                 |
| discussion  | [150, 162] (`idx%3 · 6`)     | line 142                 |
| memory      | [150, 174] (`idx%4 · 8`)     | line 154                 |
| file        | [216, 224] (`(idx%3-1)·4`)   | line 128                 |
| symbol      | parent ± [18, 27]            | line 177                 |

### Non-overlap of *different kinds* within one domain

Treat each rendered glyph as a disc of radius ρ ≤ 12 px (the renderer's
node radius is well under this). Two slots at the same anchor with radii
`r₁, r₂` and angles `θ₁, θ₂` have Euclidean distance

    d² = r₁² + r₂² − 2 r₁ r₂ cos(θ₁−θ₂)

We need `d > 2ρ`, i.e. `d > 24`.

**Case A — disjoint radius shells.** When the radius intervals are
disjoint, `d ≥ |r₁−r₂|` (triangle inequality, achieved at `θ₁=θ₂`).
Computed gaps:

- mcp(50) ↔ setup[70,78]:        ≥ 20 — *requires angular check*
- setup[70,78] ↔ tool_hub(140):  ≥ 62  ✓
- tool_hub(140) ↔ disc[150,162]:  ≥ 10 — *requires angular check*
- disc/mem[150,174] ↔ file[216,224]: ≥ 42  ✓
- mcp(50) ↔ tool_hub(140):       ≥ 90  ✓

The two "requires angular check" pairs are saved by geometry, not radius:

- **mcp ↔ setup.** MCP sits at `θ = ω + π` (line 163, plus tiny jitter
  ≤ 0.25·(total−1)/2 rad). Setup sits inside `[ω − π/2.6, ω + π/2.6]`
  (line 100). Angular gap from `ω+π` to that sector is at minimum
  `π − π/2.6 ≈ 1.93 rad`. Then `d² ≥ 50² + 70² − 2·50·70·cos(1.93)`
  `= 2500 + 4900 + 2497 ≈ 9897`, `d ≥ 99 px` ≫ 24. ✓
- **tool_hub ↔ discussion.** Tool hubs use angles in `TOOL_LOCAL_ANGLE`,
  range `[−π/3.6, +π/3.6] ≈ [−0.87, 0.87]` around `ω`. Discussions center
  at `ω + 0.72π ≈ ω + 2.26` with arc half ≤ `π/6.5 + π/6 ≈ 1.01`. Closest
  angular approach: `2.26 − 1.01 − 0.87 = 0.38 rad`. With `r₁=140,
  r₂=150`: `d² ≥ 140² + 150² − 2·140·150·cos(0.38) ≈ 42100 − 39042
  = 3058`, `d ≥ 55 px`. ✓

**Case B — DISC vs MEM (overlapping radii).** Disc centers at `ω + 0.72π`,
memory at `ω − 0.72π`; angular distance `0.56π ≈ 1.76 rad`. Half-arcs are
`π/6.5 + min(π/3, 0.04·n)` (disc) and `π/6.5 + min(π/2.5, 0.03·n)` (mem),
worst-case 1.53 and 1.74. The lanes stay disjoint while `0.04·n_disc +
0.03·n_mem < 0.79 rad`. For typical lane sizes (≤10 each) the gap is
positive; for very large N the lanes can angularly meet — see Caveats.

### Symbols vs everything else

Symbols live in a disc of radius ≤ 27 px around their parent file at
`r ∈ [216, 224]`. The nearest non-file kind by radius is discussion/memory
(top of [150,174]). Worst case: symbol on the inward edge of its parent's
petal (`r ≈ 216 − 27 = 189`) vs a memory at `r = 174` *at the same angle*
gives `d ≥ 15 px`. **This is below the 24 px collision threshold in the
worst-case angular alignment.** However, symbols inherit their parent
file's angle (which orbits a tool hub near `ω`), while memory lives near
`ω − 0.72π`. The angular gap is therefore ≥ `0.72π − file_arc/2 −
memory_arc/2 ≈ 2.26 − 0.18 − 1.74 = 0.34 rad`, giving
`d² ≥ 189² + 174² − 2·189·174·cos(0.34) ≈ 4174`, `d ≥ 64 px`. ✓

### Independence audit

Discovery: planetary-shell analogy + Fibonacci intuition. Proof: triangle
inequality + interval arithmetic on the source's literal constants. The
proof never invokes "shells balance"; it computes `d²` directly. Shared
assumption: only `|cos|,|sin| ≤ 1`. **Independence holds.**

## Conclusion

- **Boundedness & finiteness:** verified unconditionally.
- **Cross-kind non-overlap within a domain:** verified for every pair
  *except* DISC vs MEM at very high lane counts.
- **Symbol vs non-file:** verified via angular sector separation (≥ 64 px).
- **O(1) per node, O(domains×kinds) state:** verified by inspection.

Status: **verified with one named caveat.** Confidence: high — discovery and
proof are independent and agree.

## Caveats / hand-offs

- **DISC↔MEM angular collision at high N.** Lanes can meet when
  `0.04·n_disc + 0.03·n_mem ≳ 0.79 rad`. Fix: cap the additive arc growth
  (`min(π/3, …)` and `min(π/2.5, …)`) tighter, or push memory to a smaller
  radius. Hand to **Dijkstra** for a formal invariant; **Fermi** can size
  the realistic N envelope from production data.
- **Cross-domain non-overlap** is *not* proven here — it depends on
  `base_radius`'s `shell·√(N/π)·0.65` choice vs the per-domain bounding
  disc (≈ FILE_R + symbol radius ≈ 247). Out of scope for this audit; the
  heuristic argument in the docstring (line 60-66) is plausible but not
  proved. Hand to **Lamport** for a TLA-style invariant on inter-domain
  spacing.
- **Renderer glyph radius ρ.** Audit assumed ρ ≤ 12 px. Verify in
  `ui/unified/js/workflow_graph.js` style block before relying on the
  24 px threshold.
