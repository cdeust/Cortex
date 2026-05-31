# Erlang audit — layout authority capacity, blocking, and tip-over

**Discipline:** Erlang (1909, 1917). Measure λ and μ, compute ρ, derive
blocking probability from finite-capacity formulas, identify the tier
where ρ → 1 first. No optimisation before the math.

## 1. System decomposition

```
build worker  ──submit──▶  per-priority deques  ──pop──▶  authority worker  ──emit──▶  SSE per-client queues  ──flush──▶  browser
   λ events/s              c=1, K_p slots                  μ ≈ 7.28·10^5/s         δ ≈ 5·10^4/s/client       (network)
```

Three serial tiers, each with finite capacity. The composite system
fails at the **first** tier whose offered load A = λ/μ_tier exceeds 1
(Move 1: arrival-service balance).

## 2. Measured parameters (sources)

| Symbol | Value | Source |
|---|---|---|
| μ_authority | 7.28·10⁵ events/s | knuth.md integration bench, run 2 |
| K_P0..P6 | 1 000 / 1 000 / 16 000 / 32 000 / 64 000 / 128 000 / 100 | `layout_authority_scheduler.QUEUE_SIZES` |
| K_log_ring | 500 000 events | `layout_authority_log._EVENT_LOG_CAP:42` |
| K_sse_subscriber | 100 000 events | `layout_authority_log._SUBSCRIBER_QUEUE_CAP:43` |
| δ_sse | 5·10⁴ events/s/client | localhost-SSE assumption (loopback ~8 Gbit, ~200 B/event ⇒ 5·10⁶/s wire ceiling; Python json+queue dominates → 50k as the per-client realistic drain) |
| service-time CV² | ~0.4 (sub-exponential, dispatch chain) | knuth.md run-to-run variance < 7% |
| seed_project node count | 10⁶ nodes + 4·10⁶ edges | knuth.md workload table |

Service-time CV² ≈ 0.4 (sub-exponential), so M/M/1/K is a conservative
upper bound; Pollaczek-Khinchine would lower predicted queueing delay by
~30 % at the same ρ. We provision against the upper bound.

## 3. Tier 1 — per-priority deques (finite-capacity loss queues)

Each deque is **independent** under strict-priority drain — the
authority drains P0 fully before P1, P1 before P2, etc. (Move 5 with
priority displacement, Hamilton's domain). For the **lowest-priority
deque that is non-empty**, the upstream service rate is μ_authority;
higher-priority deques effectively see μ = ∞ unless they themselves are
full at the same instant.

For each priority p, model the deque as M/M/1/K_p with
ρ_p = λ_p / μ_authority. Erlang loss formula for finite buffer:

```
P_block(K, ρ) = ρ^K · (1-ρ) / (1 - ρ^(K+1))     (ρ ≠ 1)
P_block(K, 1) = 1 / (K+1)
```

### 3a. Nominal load (sustained)

Assume seed_project at sustained λ = μ_authority / 2 = 3.64·10⁵ events/s
(the producer cannot outrun the worker indefinitely — Little's Law,
Move 3). Per-priority share from knuth workload:

| Priority | items | share | λ_p (events/s) | ρ_p | K_p | P_block_p |
|---|---|---|---|---|---|---|
| P0–P2  | trivial    | < 10⁻⁴ share | < 10⁴/s | < 0.02 | ≥ 1 000 | < 10⁻³⁰⁰⁰ |
| P3 other  | 619 920 | 0.620  | 2.26·10⁵ | 0.310 | 32 000 | < 10⁻¹⁶⁰⁰⁰ |
| P4 symbol | 250 000 | 0.250  | 9.1·10⁴  | 0.125 | 64 000 | < 10⁻⁵⁰⁰⁰⁰ |
| P5 edge   | 4·10⁶   | (×4 nodes) | δ-bounded | — | 128 000 | see §3b |

At sustained nominal load, **no priority blocks**. Every deque sits at
ρ < 0.5; we are deep on the flat part of the hyperbola.

### 3b. Bursty load (λ = 10·μ for 100 ms)

Producer bursts at λ_burst = 10·μ = 7.28·10⁶ events/s for Δt = 0.1 s.
Total burst = 7.28·10⁵ events. Drain rate during burst = μ. Net
accumulation = 9·μ·Δt = 6.55·10⁵ events.

ρ_burst = 10. The closed-form Erlang B at ρ ≥ 1 collapses to
P_block(K,ρ) → (ρ−1)/(ρ − ρ^{−K}) ≈ 1 − 1/ρ. For ρ=10: **P_block ≈ 0.90**
on whichever priority absorbs the burst. The burst distributes
proportionally to the workload mix (§3a):

| Priority | burst items | K_p | overflow drops |
|---|---|---|---|
| P0..P2   | < K_p | — | 0 |
| P3       | 4.06·10⁵ | 32 000 | **3.74·10⁵ dropped** |
| P4       | 1.64·10⁵ | 64 000 | **1.00·10⁵ dropped** |
| P5 edge  | (×4) 2.91·10⁶ | 128 000 | **2.78·10⁶ dropped** |

**Burst verdict: P5 edges absorb 95 % of the drops; P3+P4 nodes drop
~470 k.** This is by-design (edges drop before nodes; Hamilton's
priority-displaced shedding). The deque tier behaves as advertised.

## 4. Tier 2 — authority worker (single-server bottleneck)

c = 1, μ = 7.28·10⁵ /s. By Move 1, **the system tips into sustained
backlog at λ ≥ μ**, i.e. at any sustained input above ~728 k events/s.
Utilisation–latency curve (M/M/1, Move 2):

ρ = 0.5 → W = 2× service time; 0.7 → 3.3×; 0.8 → 5×; 0.9 → 10×;
0.95 → 20×; 0.99 → 100×.

**The knee is at ρ ≈ 0.7** (W = 3.3·service_time). Provision so that
sustained λ ≤ 0.7·μ ≈ **510 k events/s**.

## 5. Tier 3 — SSE per-client queues

Each client has K_sse = 100 000 slots, drained at δ ≈ 5·10⁴ /s. Offered
load per client = full authority output = μ ≈ 7.28·10⁵ /s.

ρ_sse = μ / δ = **14.6** — catastrophically over capacity.

P_block(100 000, 14.6) ≈ 1 − 1/14.6 = **0.93**. **The SSE tier is the
binding bottleneck**, not the deques and not the worker. At any
sustained authority output above δ ≈ 50 k/s **per client**, the SSE
queue fills in under 2 s (100 000 / (7.28·10⁵ − 5·10⁴) = 0.15 s) and
stays full, dropping 93 % of events.

The 500 k-event log ring (§ knuth.md) backs this up: at μ=728 k/s the
ring wraps every **0.69 s**, forcing every SSE client whose lag exceeds
that to take the gap-snapshot path (already implemented; correct
behaviour by I3).

## 6. Bottleneck ranking

| Rank | Tier | Tip-over λ | Sustained P_block at λ=μ |
|---|---|---|---|
| 1 (binding) | SSE per-client | δ ≈ 5·10⁴ /s | 0.93 |
| 2 | authority worker | μ = 7.28·10⁵ /s | 1.00 (queue grows unbounded) |
| 3 | priority deques (P5 edge, then P4 symbol) | depends on burst shape | < 10⁻³ at sustained ρ ≤ 0.5 |
| 4 | log ring (gap-fallback path) | μ until lag > 0.69 s | gap-snapshot triggered, not data loss |

**The system is SSE-bound by a factor of ~15× over the worker.** No
amount of worker optimisation moves the binding constraint.

## 7. Little's Law sanity check

At the binding constraint (SSE), L = λ·W. With δ=50 k/s and target
W ≤ 1 s end-to-end client latency: L ≤ 50 000 events in flight per
client. Current K_sse = 100 000 → **2× the steady-state need**. Cap is
correctly sized for the drain rate, not for the producer rate.

## 8. Recommended queue sizes (minimise total drops)

The deque caps are already conservative. The mismatch is at the SSE
boundary. Two distinct levers:

**(a) Match SSE cap to drain rate × tolerated lag.** Current 100 000 ÷
50 000/s = 2 s of lag absorption. Adequate for transient bursts,
ineffective against sustained overload (no buffer can fix ρ > 1; Move 1).

**(b) Throttle authority emission to per-client δ when an SSE client
is the only consumer.** This is the correct fix: the worker should not
run faster than the slowest SSE client minus a margin. Otherwise the
ring-gap path triggers continuously and the client lives on snapshots,
not deltas.

**Concrete recommendations:**

| Tier | Current | Recommended | Rationale |
|---|---|---|---|
| P0 domain     | 1 000   | 1 000   | unchanged — saturates at < 10⁻³⁰⁰⁰ |
| P1 tool_hub   | 1 000   | 1 000   | unchanged |
| P2 file       | 16 000  | 16 000  | unchanged |
| P3 other      | 32 000  | 32 000  | unchanged — burst drops are by-design |
| P4 symbol     | 64 000  | 64 000  | unchanged |
| P5 edge       | 128 000 | 128 000 | unchanged — first-to-drop is correct |
| P6 subtree    | 100     | 100     | coalesced; correctly tiny |
| log ring      | 500 000 | 500 000 | gap-fallback handles overflow |
| SSE per-client| 100 000 | **100 000 + emission throttle** | cap is fine; **add producer-side rate limiter at min(δ_clients) · 0.7** |

## 9. Retry amplification check

SSE clients reconnect on disconnect with snapshot-then-delta protocol.
If reconnect rate r and snapshot cost = full graph (1 M nodes), then
effective λ_eff = λ + r · N. At r = 1 reconnect/s (one flapping client)
and N = 10⁶, λ_eff = λ + 10⁶/s — **single flapping client alone exceeds
worker capacity**. Mitigation: snapshot must be served from a
pre-computed tile cache (already true per `mcp_server/handlers/quadtree_handler.py`),
not regenerated. **Verify cache hit rate ≥ 99 % under reconnect storms.**

## 10. Hand-offs

- **Hamilton:** SSE-tier emission throttle is priority-displaced
  shedding under a different name — design the back-pressure protocol
  so the worker drops *edges first, symbols second* when δ_min < μ.
- **Maxwell:** the snapshot-on-reconnect feedback loop is a
  potential positive-feedback oscillator. Verify damping.
- **Curie:** measure δ_sse on a real browser client (the 5·10⁴/s
  number is a loopback estimate; over a real LAN to a real Chrome it
  is plausibly 1–2·10⁴/s, which would tighten the binding constraint
  by 3–5×).
- **Knuth:** worker μ=728 k/s is comfortable headroom over the SSE
  bottleneck — **do not optimise compute_slot**; the geometry path is
  not the binding constraint by ~15×.

## Files referenced

- `/Users/cdeust/Developments/Cortex/mcp_server/server/layout_authority_scheduler.py:78-86` — QUEUE_SIZES
- `/Users/cdeust/Developments/Cortex/mcp_server/server/layout_authority_log.py:42-43` — log + SSE caps
- `/Users/cdeust/Developments/Cortex/tasks/layout-authority/audits/knuth.md` — measured μ
- `/Users/cdeust/Developments/Cortex/tasks/layout-authority/cost-model.md` — geometry budget
