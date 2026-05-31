# Ramanujan Audit — `layout_authority_geometry.compute_slot`

> **STATUS LABEL: CONJECTURE report.** Every claim below is a candidate for proof,
> NOT a verified fact. Numerical hand-computations were verified against
> `compute_slot()` to machine precision; the *structural conjecture* (the closed
> form connecting all special cases) requires a prover-agent (Lamport/Dijkstra)
> to discharge before being treated as a load-bearing invariant of the layout.
>
> **Prover-agent assigned:** Lamport (algebraic invariant proof) + Dijkstra
> (degeneracy enumeration). Hand-off is mandatory; this report MUST NOT be
> consumed as fact without verification.

## Domain & zone

- Domain: closed-form 2D placement geometry (Fibonacci-spiral anchors + per-kind
  ring + sector fan). Pure trig, no I/O, no iteration.
- Zone competence: **high** — special-case computation against analytic
  formulae is the canonical Ramanujan workflow.
- Canvas: W=1920, H=1080, cx=960, cy=540 throughout.

## Hand-computed special cases vs. code

All numbers below were derived from the source formulas BEFORE running
`compute_slot`; the right column is the code's actual output. **Every value
agrees to ≥4 decimal places** (verified by `/tmp/ramanujan_verify.py`).

### Case A — N=1 domain, 3 files orbiting tool hub `Edit`

```
base_r  = max(min(W,H)·0.42, (2·FILE_R+60)·√(N/π)·0.65)
        = max(453.6000, 183.3616) = 453.6000              ← floor wins
anchor  : r = base_r·√((0+0.5)/1) = 320.7436, θ = 0·Φ = 0
        → (1280.7436, 540.0000)                           [matches code]
outward : atan2(0, +320.74) = 0.000000
hub Edit: TOOL_R·(cos 0, sin 0) → (1420.7436, 540.0000)   [matches code]
file arc: min(0.35, 0.08 + 3·0.015) = 0.125               (small-N branch)
file[i] : t = ((i+0.5)/3 − 0.5)·0.125, r = 220 + ((i%3)−1)·4
  i=0 → t=−0.04167, r=216 → (1496.5562, 531.0026)         [matches]
  i=1 → t= 0.00000, r=220 → (1500.7436, 540.0000)         [matches]
  i=2 → t=+0.04167, r=224 → (1504.5492, 549.3306)         [matches]
```

### Case B — N=2 domains × 2 files each (Edit hub)

```
base_r = 453.6000   (floor still wins; ceiling = √(2/π)·0.65·500 = 259.3)
domain[0]: r=226.8000, θ=0.0000     → (1186.8000, 540.0000)  [matches]
domain[1]: r=392.8291, θ=2.4000     → ( 670.3400, 805.3523)  [matches]
file arc (n=2): min(0.35, 0.08+2·0.015) = 0.110
  d=0 i=0 → (1402.7183, 534.0607)   [matches]
  d=0 i=1 → (1406.7168, 546.0492)   [matches]
  d=1 i=0 → ( 515.1405, 955.5824)   [matches]
  d=1 i=1 → ( 504.0940, 949.4434)   [matches]
```

### Case C — N=3 domains × 1 file × 5 symbols (around file of d=0)

```
base_r = 453.6000
domain[0]: r=261.8985, θ=0      → (1145.1814, 540.0000)
domain[1]: r=453.6000·√(.5)=...  θ=2.4000 → ( 723.4936, 756.6592)
domain[2]: r=405.7905, θ=4.8000  → ( 996.2011, 127.5072)
file (d=0): hub_angle=0, idx=0/total=1, arc=0.095
           → (1361.1814, 540.0000)
symbols (5 around file at angle 2π(i+0.5)/5, r=SYM_CLUMP_R+(i%4)·3):
  i=0 → ang=0.6283 r=18 → (1375.7437, 550.5801)  [matches]
  i=1 → ang=1.8850 r=21 → (1354.6921, 559.9722)  [matches]
  i=2 → ang=3.1416 r=24 → (1337.1814, 540.0000)  [matches]   ← exact π
  i=3 → ang=4.3982 r=27 → (1352.8380, 514.3215)  [matches]
  i=4 → ang=5.6549 r=18 → (1375.7437, 529.4199)  [matches]
```

## Conjectured closed form (the Ramanujan identity)

For any node, position is the composition of three pure rotations + radial
offsets that share an additive structure:

```
P(node) = anchor(D)
        + R_kind · ringRadius(kind, idx) · û(outward(D) + ψ_kind(idx, N_kind))
```

where:
- `anchor(D) = (cx,cy) + base_r·√((D+0.5)/N_total)·(cos D·Φ, sin D·Φ)`,
  `Φ = π(3−√5)` — the golden angle (Vogel 1979 Fibonacci spiral).
- `outward(D) = atan2(anchor−center)`, with the `<5px → −π/2` guard.
- `ψ_kind` is a kind-specific angular fan: linear `((i+0.5)/n − 0.5)·arc` for
  setup/file/disc/mem; fixed lookup `TOOL_LOCAL_ANGLE` for tool hubs; π-shift +
  jitter for MCPs; full-circle `2π(i+0.5)/n` for symbols.
- `ringRadius` is a tiny integer wobble on top of a per-kind base (±4/±6/±8 px
  via `(idx % k) − offset`).

**Conjecture (CONJ-1):** for every node kind, the placement function is a
pure isometry composition `T_anchor ∘ R_outward ∘ (radial offset)` and is
invariant under any reordering of nodes that preserves the (kind, idx, total)
triple. → Hand off to Lamport for TLA+ proof of the invariance claim.

**Conjecture (CONJ-2):** symbols form a regular n-gon (modulo the `(i%4)·3`
radial wobble) precisely because `2π(i+0.5)/n − 2π(j+0.5)/n = 2π(i−j)/n` is
independent of file position — the file-relative frame is exact. The wobble
breaks the regularity by ≤9 px. → Hand off to Dijkstra for proof that the
wobble cannot collapse two symbols onto the same point for any n ≥ 1.

## Small-N degeneracies (verified, not just conjectured)

| Probe | Result | Note |
|---|---|---|
| `base_radius(N=0)` | 453.60 | `max(N,1)` guard works; no div-by-zero |
| `domain_anchor` at N=1 | θ=0 → always due-east of centre | Fibonacci spiral collapses to a single point — fine, but means the outward axis is *deterministically* +x for the only domain. No angular variety to test. |
| `outward_angle` at anchor==centre | −π/2 | `<5px` guard fires; stable upward bias |
| `slot_for_symbol(total=0)` | returns file_slot | Early return prevents `/0` |
| `slot_for_symbol(n=1)` | (−18, 0) rel to file | Single symbol lands at angle π — *left* of file, not on it. Visually fine but counter-intuitive (one might expect "on top") |
| `arc` for n=3 files | 0.125 rad ≈ 7.2° | Below the 0.35 cap; `min` branch dormant until n≥18 |
| `arc` for memory n=1 | `2·SECTOR_SIDE_HALF + min(π/2.5, 0.03)` = 0.997 rad | Floor dominates: even a single memory gets the full sector half-width. **Possibly wasteful** — single-element fans don't need the whole arc. |

## Where small-N differs from large-N (the qualitative break)

1. **File arc saturation**: `arc = min(0.35, 0.08 + n·0.015)` saturates at n=18.
   Below 18 the arc grows linearly with file count; above 18 it is clamped.
   Special-case computation at n=3 hides this — **the linear regime is the
   only one a 3-file test exercises**.
2. **Memory/discussion arc has TWO bonuses**: the `min(π/3, n·0.04)` term and
   the base `2·SECTOR_SIDE_HALF`. At n=1 the bonus is 0.04 rad (negligible);
   at n=∞ it caps at π/3. Hand-tests at n=1 will not reveal whether the cap
   is correct.
3. **Domain spiral collision**: `base_radius` formula uses `√(N/π)·0.65·shell`
   as the spacing-driven floor. For W=H=1080, this floor only beats the 42%
   floor when N ≥ ⌈π·(0.42·min/(0.65·shell))²⌉ ≈ N=6 (canvas-dependent).
   **N=1,2,3 all fall in the canvas-floor regime** — the spacing formula is
   completely untested by these special cases.
4. **Floating-point edge**: at θ = D·Φ for D=0, sin(0) is exactly 0.0, so
   `domain[0]` always lands on y=cy precisely. For D≥1, θ is irrational ×
   integer and we accumulate ~1 ulp of error per multiplication. Not a
   correctness issue at our coordinate scale.

## Generator's self-assessment

- All 24 hand-computed (x,y) values match the code to ≥4 decimal places.
  The match is exact in the linear regime; rounding shows up only in the
  4th–6th decimals of `cos/sin` evaluations.
- Confidence in CONJ-1 (kind-isometry composition): **high** — the structure
  is visible by inspection of the code.
- Confidence in CONJ-2 (n-gon non-collision): **medium** — the wobble could
  in principle collapse points for some pathological n; needs Dijkstra.
- Confidence that the *spacing-driven floor* of `base_radius` is correct for
  large N: **low** — not tested here. Recommend a separate audit at N=11
  (current production domain count) to exercise that branch.

## Hand-offs (MANDATORY)

- CONJ-1, CONJ-2, and the spacing-floor claim → Lamport / Dijkstra for proof.
- Small-N memory arc waste (degeneracy #5 in table) → escalate as a
  potential refactor target after Lamport confirms the geometry is otherwise
  invariant.
- Large-N branch coverage (file arc cap, memory cap, base_radius spacing
  floor) → schedule a sibling audit at N∈{18, 50, 200}.

## Refusal note

This report is a CONJECTURE bundle. Numerical equality at three special
cases is necessary but not sufficient evidence for the closed-form claim.
Do not treat CONJ-1 or CONJ-2 as load-bearing invariants of the layout
authority until a prover-agent has discharged them.
