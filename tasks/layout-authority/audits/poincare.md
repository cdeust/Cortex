# Poincaré — Qualitative dynamics of the layout authority

**Method:** Poincaré 1890. Do not solve. Characterise. Map the
phase portrait of (λ, δ), name the fixed points, classify their
stability, locate the bifurcation curves, and predict the visible
symptom in each region. The number is Erlang's job; the shape is mine.

## 1. State variables and reduction

Full state of the authority is high-dimensional: seven priority deque
depths, the log-ring write head, every SSE client's queue depth,
`k_retry`, `emit_permitted`. By Erlang §6 the **binding constraint is
the SSE per-client queue**, drained at δ; everything upstream is ≥15×
faster. The slow manifold of the system collapses to two state
variables:

  Q  = SSE backlog (one client, worst case), 0 ≤ Q ≤ K_sse = 1·10⁵
  R  = retry-amplification gain k_retry, ≥ 0

driven by two control parameters:

  λ  = sustained event rate from build worker (events/s)
  δ  = subscriber drain rate (events/s/client)

Effective arrival rate at SSE: λ_eff(λ, R) = λ · (1 + R · 𝟙[Q=K_sse]).
The shedding governor turns retries on when Q saturates; Maxwell's
proposed speed-controller would turn λ down when Q approaches K_sse.

## 2. Fixed points (no incubation needed; algebra is qualitative)

dQ/dt = λ_eff − δ. Set to zero.

| Name | Location | Existence condition | Stability |
|---|---|---|---|
| **F₀ healthy** | Q* = 0, R* = 0 | λ < δ | **stable node** (both eigenvalues negative if no retry) |
| **F₁ saturated** | Q* = K_sse, R* > 0 | λ ≥ δ | **unstable** if k_retry ≥ 1 (Maxwell §2); **stable** if k_retry < 1 |
| **F₂ throttled** | Q* < K_sse, λ_throttled = δ | speed-controller engaged & λ_raw > δ | **stable spiral** (Maxwell band gives damping) |

F₀ and F₂ are the only attractors a healthy system should sit at.
F₁ is a saddle whose unstable manifold is the retry-storm trajectory.

## 3. Bifurcation curves on the (λ, δ) plane

```
   δ (drain, events/s/client)
   ↑
   |   I  HEALTHY                    (F₀ globally attracting)
   |  ─────────────────  λ = δ        ← transcritical bifurcation
   |   II  COMPENSATED OVERLOAD
   |        (Q grows toward K_sse, drops begin, R still ≈ 0)
   |  ─────────────────  λ = δ·(1 + ε_retry_threshold)
   |   III  HOPF / LIMIT CYCLE
   |        (drop ↔ recover oscillation; k_retry crosses 1)
   |  ─────────────────  λ ≈ μ_authority ≈ 7.28·10⁵
   |   IV  RUNAWAY
   |        (worker itself overloads; backlog grows on every tier)
   +─────────────────────────────────→ λ
```

Three codimension-1 boundaries:

- **B₁: λ = δ** — transcritical. Below: Q decays to 0. Above: Q rises
  monotonically to K_sse on a timescale K_sse/(λ−δ). Erlang gives the
  number (e.g. 0.15 s at λ=μ); I give the shape — a ramp, not a
  resonance, until B₂ is crossed.
- **B₂: k_retry(λ, δ) = 1** — Hopf bifurcation. F₁ loses stability; a
  limit cycle is born. This is exactly Maxwell's "growing oscillation"
  threshold at §2. Empirically B₂ sits just above B₁ because viewport
  drag + SSE auto-reconnect both refire on missing data → k_retry > 1
  almost the instant Q hits K_sse.
- **B₃: λ = μ_authority** — second saturation. Now the worker queue
  also grows; deque P5 then P4 begin to drop (Erlang §3b). This is a
  *fold* on the upstream variable: drops cascade up the priority
  ladder.

## 4. The four regions and their visible symptoms

| Region | Phase-space description | Predicted symptom (what an operator sees) |
|---|---|---|
| **I  HEALTHY** (λ < δ) | Single global attractor F₀. All trajectories decay exponentially to zero backlog. Time-constant ≈ 1/(δ−λ). | SSE clients show steady frame rate, no gap-snapshots, `is_overloaded()` returns False. |
| **II  COMPENSATED OVERLOAD** (δ < λ < δ·(1+ε)) | F₀ destroyed; F₁ stable. Q saturates at K_sse, dropping at rate (λ−δ). No retry yet. | Steady stream of dropped events; clients see staleness but no oscillation; gap-snapshot path triggers on lag > 0.69 s (Erlang §5). **Observable: drop counter rising linearly, frame rate steady but stale.** |
| **III  LIMIT CYCLE** (λ above the Hopf curve) | F₁ becomes unstable spiral. Trajectory orbits a closed curve in (Q, R) space with period T ≈ τ_loop · 2π / √(k_retry − 1). With τ_loop ≈ 10 ms and k_retry ≈ 1.5, **T ≈ 90 ms ⇒ ~11 Hz oscillation**. | Visible "breathing" of the graph: nodes appear, vanish, reappear. Reconnect storms. CPU sawtooths. **This is the failure mode operators report as "the viz keeps flapping."** |
| **IV  RUNAWAY** (λ > μ_authority) | F₁ unbounded; deque tier saturates upstream; trajectory diverges along the priority ladder (edges drop first, then symbols, then files). | Total visualisation collapse. The qualitative character is no longer oscillation — it is monotone loss. Edges disappear permanently, then symbols, then domains. Recovery requires full reseed. |

## 5. Basin of attraction for HEALTHY (F₀)

In the open-loop (current shedding-only) system the basin of F₀ is
exactly Region I — **the healthy attractor exists only when λ < δ at
every instant**. Any sustained excursion across B₁ permanently leaves
the basin until λ falls back; if k_retry ≥ 1, the excursion
self-amplifies (Region III) and the basin is not re-entered without
an external reset.

With Maxwell's speed-controller installed (the F₂ attractor opens up):
**the basin of {F₀ ∪ F₂} expands to all (λ, δ) with λ_raw < μ_authority**.
The throttle moves the system off its unstable manifold by clamping
the producer to δ. This is the qualitative payoff Maxwell quantifies:
F₂ replaces the limit cycle in Region III with a stable spiral.

## 6. Topological equivalence to a known problem

The (Q, R) dynamics are topologically equivalent to the **Watt
governor on a flywheel with delayed feedback** (Maxwell 1868). Same
two state variables (load, gain), same two parameters (drive, drain),
same Hopf bifurcation when delay·gain > 1. The cure is the same:
hysteresis band + integrator, exactly Maxwell §4.

They are also equivalent to a **predator-prey system** with retries as
predator and queue capacity as prey — Lotka-Volterra orbits in the
unstable region. The 11 Hz "breathing" is the predator-prey limit
cycle.

Recognising the equivalence imports the cure: damping = deadband (§4
of maxwell.md), gain·delay margin = 2.5× (verified by Maxwell §3).
No new mathematics is needed.

## 7. Cross-check against Erlang and Maxwell

| Audit | Their finding (numerical) | My finding (qualitative) | Agree? |
|---|---|---|---|
| Erlang §5 | P_block(SSE) = 0.93 at λ=μ | Region II/III: F₀ destroyed for λ > δ | ✓ same boundary B₁ |
| Erlang §9 | one flapping client → λ_eff > μ alone | Region III & IV reachable from a single stuck subscriber | ✓ basin escape via R |
| Maxwell §2 | shedding unstable when k_retry ≥ 1 | Hopf bifurcation B₂ at k_retry = 1 | ✓ same threshold |
| Maxwell §3 | speed control moves loop to gain·delay = 2.5× margin | F₂ opens; basin of attractor set expands to all λ < μ | ✓ same cure |
| Maxwell §4 | three-poll deadband to suppress bang-bang | hysteresis collapses limit cycle to stable spiral | ✓ same mechanism |

The three audits triangulate. Erlang sets the numerical thresholds;
Maxwell proves stability is gain·delay-bounded; Poincaré classifies
the *kind* of failure in each region so the operator-visible symptom
can be predicted before the failure happens.

## 8. Operational implication — symptom-to-region inverse map

For SRE / runbook use. Given an observed symptom, locate the region:

| Observed symptom | Region | First action |
|---|---|---|
| Frame rate smooth, no drops | I | nothing — system is in F₀ |
| Drop counter rising linearly, frame rate steady-stale | II | reduce λ (back-pressure) or raise δ (faster client); single fixed point — will not self-recover but will not worsen either |
| Frame rate oscillating at ~5–20 Hz, reconnect storms | III | **install speed-controller (Maxwell)** — shedding alone cannot exit this region |
| Edges, then symbols, then files vanishing in priority order | IV | full reseed; producer rate exceeds worker capacity, not just drain |

## 9. Refusal conditions

- **k_retry assumed ≥ 1, not measured.** The Hopf curve B₂ position
  depends on this; if Curie measures k_retry < 1 in production, Region
  III collapses into Region II and the limit-cycle prediction is
  spurious. Maxwell §8 raises the same concern.
- **Single-client reduction.** A multi-client SSE fanout has δ_eff =
  min over subscribers; the slowest client sets the boundary B₁.
  Per-client basin computation is left to a follow-up (one Poincaré
  section per client).
- **Slow-manifold reduction assumes upstream tiers are fast.** Valid
  while λ < μ_authority. Region IV breaks the reduction; analyse
  upstream queues separately (Erlang §3b already does this).

## 10. Hand-offs

- **Erlang** — bifurcation curve B₃ is exactly your tip-over at λ=μ;
  the qualitative regions agree with the numerical thresholds.
- **Maxwell** — the F₂ attractor your speed-controller creates is the
  qualitative justification for the gain·delay-margin calculation.
- **Curie** — measure k_retry over a 60 s window of induced overload;
  the position of B₂ on the (λ, δ) plane is the load-bearing unknown.
- **Mandelbrot** — the limit-cycle period (~90 ms) and the priority-
  ladder cascade in Region IV both have self-similar structure; worth
  a fractal-dimension look at the log-ring waveform.
- **Hamilton** — priority-displacement is the *boundary condition*
  that selects which deque saturates first when trajectory enters
  Region IV. Same governor at the priority-deque scale.
