# Laplace audit — Bayesian forecasts of drop, tail-latency, and replay-miss

**Discipline:** Laplace (1774, 1812, 1814). State the prior; state the
likelihood; compute the posterior. Every probability is a state-of-knowledge
claim, not a frequency. Hypothesis space is exhaustive (`other / model
wrong` included).

## 1. Given parameters

| Symbol | Value | Source |
|---|---|---|
| λ_arr | 10^4 events/s, Poisson | user-stated |
| δ_sub | 5·10^4 events/s | user-stated |
| Build T | 60 s ⇒ N = 6·10^5 events | derived |
| Kind mix | symbol 0.60, file 0.20, mem 0.15, other 0.05 | user-stated |
| K_sse | 100 000 | erlang.md §2 |
| K_log_ring | 500 000 | erlang.md §2 |
| μ_authority | 7.28·10^5/s | knuth.md run 2 |

**Regime check.** ρ_sse = λ/δ = **0.20**; ρ_worker = λ/μ ≈ **0.014**. Both
deeply on the flat M/M/1 curve. Erlang's audit assumed worst-case λ=μ;
under the user's nominal load the system runs at **1/15 of the binding
constraint**. This dominates every posterior below.

## 2. Prior (state of knowledge before computing)

| Failure mode | Prior P | Source |
|---|---|---|
| H1: SSE per-client overflow | 0.93 *if ρ ≥ 1*, else ≪ 0.05 | erlang.md §5 |
| H2: median latency > 100 ms | 0.50 at ρ=0.7, ≪ 0.05 at ρ < 0.3 | erlang.md §4 |
| H3: client misses replay window | depends on ring residency vs reconnects | erlang.md §9, fermi.md |
| H4: other / model wrong | 0.05 baseline | taleb.md §2 |

Priors are weakly informative — anchored to audit regime predictions, not
to measured base rates.

## 3. P(any drop in a 1-min build) — H1

**Steady state.** M/M/1/K with ρ=0.2: P_block ≈ 0.2^(10^5) — operationally
zero (below double-precision underflow). Union over N=6·10^5 events ⇒
P(any drop in 60 s) ≈ N · P_block ≈ 10^−69 996. Negligible.

**100 ms burst at 10× nominal.** ρ_burst=2 for Δt=0.1 s. Net accumulation
into K_sse ≈ (λ_burst − δ)·Δt = 5·10^3 events. Far below K_sse = 10^5.
**No drop from a single burst.** Fill time for sustained 10× burst =
K_sse / (λ_burst − δ) = **2 s** before first drop. Discovery bursts last
~100 ms (fermi.md), so drop requires multi-burst storm or
reconnect-amplification (erlang.md §9).

| Sub-hypothesis | Posterior P |
|---|---|
| H1a: drop under steady Poisson(10^4) | < 10^−10 |
| H1b: drop under one 100 ms 10× burst | < 10^−6 |
| H1c: drop under repeated-burst / reconnect storm | **0.03–0.10** |
| **H1 total** | **≈ 0.03–0.10** |

The Erlang prior of 0.93 was conditional on ρ≥1; at ρ=0.2 it collapses by
~10^−4. The user-visible drop probability is dominated by H1c.

## 4. P(median latency > 100 ms) — H2

**Queueing alone.** Mean wait W = ρ/(1−ρ) · (1/μ). At worker ρ=0.014:
W ≈ 20 ns. At SSE ρ=0.2: W_sse ≈ 5 µs. Add SSE network + browser parse:
**~1 ms typical, ~10 ms p99.** P(median > 100 ms | queueing only) < 10^−9.

**Three pathways that can push median above 100 ms:**

1. **Python GC / GIL stall.** Observed pause rate ~0.1%/s in long-running
   workers (taleb.md fragility on `layout_authority.py`). P(any pause in
   60 s) ≈ 1 − 0.999^60 ≈ **0.058**.
2. **Reconnect-snapshot regen.** Cache hit ≥ 99% per erlang.md §9.
   P(reconnect during build) · P(cache miss) ≈ 0.05 · 0.01 = **5·10^−4**.
3. **Schema drift / NaN propagation** (fermi.md). Assume P ≈ 0 nominal.

| Sub-hypothesis | Posterior P |
|---|---|
| H2a: queueing pushes median > 100 ms | < 10^−9 |
| H2b: GC / GIL stall in 60 s | **0.058** |
| H2c: snapshot regeneration | 5·10^−4 |
| **H2 total** (~independent union) | **≈ 0.06** |

The dominant slow-tail source is **runtime, not queueing**. Erlang's
ρ-knee is correct but irrelevant at ρ=0.2.

## 5. P(mid-build client outside replay window) — H3

**Replay window.** K_log = 5·10^5 events at λ=10^4/s ⇒ residency
**T_res = 50 s**. Build is 60 s ⇒ first 10 s of events are evicted before
the build ends.

**Indifference prior on connect time.** Uniform on [0, 60] s
(Laplace's principle of indifference; no informative prior on tab-open
behavior). P(t > T_res | client connects mid-build) = 10/60 = **0.167**.

**Total probability over user-behavior scenarios:**

| Scenario | P(scenario) | P(≥1 connect in 60 s) |
|---|---|---|
| Solo dev, no flapping | 0.6 | 0.10 |
| Active session, multi-tab | 0.3 | 0.40 |
| Flapping / dead-subscriber | 0.1 | 0.95 |

P(≥1 client outside window) = Σ P(scenario)·P(connect)·0.167
  = 0.6·0.10·0.167 + 0.3·0.40·0.167 + 0.1·0.95·0.167
  ≈ 0.010 + 0.020 + 0.016 ≈ **0.046**.

But gap-snapshot fallback is implemented (erlang.md §9, quadtree handler).
"Outside window" is **handled, not fatal**. The 0.046 is *raw exposure*.

| Sub-hypothesis | Posterior P |
|---|---|
| H3a: outside window AND fallback works | ≈ 0.046 (benign) |
| H3b: outside window AND fallback fails | 0.046·0.01 ≈ **5·10^−4** |
| H3c: kind-mix shifts residency | < 0.005 |
| **H3 user-visible failure** | **5·10^−4 to 5·10^−3** |

Kind-mix is **favorable**: 60% symbols are lowest SSE-displacement
priority (Hamilton), so under pressure they drop first, lengthening
effective replay window for files / memories.

## 6. Joint posterior — 1-min build

| Outcome | Posterior P | Severity |
|---|---|---|
| Any drop on any client | 0.03–0.10 | low (mostly P5 edges, by-design) |
| Median latency > 100 ms | ≈ 0.06 | low (GC, recoverable) |
| Mid-build client outside replay (raw) | ≈ 0.046 | benign (fallback works) |
| Outside replay AND fallback fails | 5·10^−4 | high if hit |
| Model misspecified (H4) | 0.05 | unbounded |

H1 / H2 / H3 are correlated (GC pause grows backlog → drop). Union bound
≈ 0.16; with positive correlation **0.10–0.18 for "at least one
observable degradation in a 1-min build."**

## 7. Calibration

- Posteriors are **prior-dominated**. No production measurements of GC
  rate, reconnect rate, or cache miss rate exist for this deployment.
- Sensitivity: H1 robust (queue math); H2 / H3 swing 3–5× on Python
  runtime tail and user-behavior priors.
- Historical calibration in this domain: **unknown** — no benchmark of
  predicted-vs-observed degradation. **Do not trust the third
  significant figure.**

## 8. Posterior predictions (information gain ranking)

1. **Measure GC pause distribution** under sustained builds — collapses
   H2's 3–5× sensitivity.
2. **Measure reconnect rate** in real sessions — distinguishes H3
   scenarios (0.10 vs 0.95).
3. **Stress test with sustained 10× burst > 2 s** — validates H1c, the
   only non-negligible drop pathway.
4. **Measure ring residency under 60% symbol mix** — symbol payload size
   may differ from 80 B/event default.

## 9. Hand-offs

- **Curie** — design measurements §8 items 1–3.
- **Erlang** — re-derive ρ-curves at λ=10^4/s; confirm queueing
  contribution to median latency is < 10 µs.
- **Taleb** — H1c (repeated-burst drop) is the only non-negligible
  steady-state fragility under nominal load.
- **Schon** — are we designing for ρ=1 (Erlang's worst case) or ρ=0.2
  (user nominal)? Right cap, rate-limiter, fallback differ by 10×.

## 10. Refusals (zetetic discipline)

- No point estimates without ranges; priors do not support 3-sig-fig
  precision.
- H4 (model wrong) retained at 0.05 — never drop the residual.
- No probability is 0 or 1. P(drop) ≈ 10^−70 000 is "operationally
  zero," not logically zero — a missing failure mode could move it.
