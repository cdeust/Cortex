# Simon Audit — Bounded-Rationality / Satisficing Catalogue

Scope: every "good enough" decision in `layout_authority_*.py`. The whole
module is satisficing-by-construction. Optimal placement (force
equilibrium) is intractable at N=10⁹: O(N log N) × hundreds of ticks ≈
10¹² ops, six orders over the 1–2 s budget. The authority substitutes a
closed-form O(1) per-node placement that is good enough because the eye
cannot distinguish spiral anchors from force-equilibrium at billion-node
zoom.

## 1. The implied per-event budget — derive from the user's target

User's satisficing target: **"1–2 s for billions"**. Make it explicit.

```
N_low  = 1·10⁹ nodes,   T_high = 2 s   →  budget_loose = 2 ns/event
N_high = 5·10⁹ nodes,   T_low  = 1 s   →  budget_tight = 0.2 ns/event
working point (cost-model §1):           1 ns/event = 3 cycles @ 3 GHz
```

3 cycles/event is the physical floor. Pure-Python is 180–300 ns/slot
(`cost-model.md` §5) — 180–300× the floor. The satisficing path: (1)
geometry O(1) per node (enforced); (2) numpy batches ~30–50 ns/slot;
(3) 8-core writes 5–8× more. SSE wire at ~80 B/event = 80 GB for 1e9 —
the user's "billions" means **billions placed, not transmitted**: wire
is satisficing at 500k replay, not archival.

Per-event budget the design implicitly satisfices to:

| Stage | Budget | Source |
|---|---|---|
| `compute_slot` (numpy) | ≤10 ns/event | cost-model §5 |
| `format_slot` SSE | ≤300 ns/event | wire bench (line 240) |
| Scheduler `submit` | ≤1 µs/event | one lock acquire, one deque.append |
| Network egress | gated by SSE drain rate, not per-event | replay buffer absorbs |

## 2. Catalogue of satisficing tradeoffs — and where each breaks

### S1 — LOD stride function (`_lod.stride`, line 58)

**Decision.** `stride(zoom) = max(1, int(2^(3 − 4·zoom)))`. A power-law
subsampling that yields `visible ≈ N / stride`. Symbols decimated by
`blake2b(node_id) % stride == 0`.

**Why it satisfices.** Optimal would be a learned importance score —
intractable (global pass, undefined "interesting"). Hash decimation is
good enough: (a) reconnect-stable, (b) uniform within ±0.5% (self-check
log-log slope ≈ −1), (c) the eye at zoom=0.25 cannot distinguish "the
right 25%" from "any uniform 25%".

**Threshold beyond which "good enough" fails.**
- **Hash non-uniformity > 5%.** Self-check tolerance is ±5% on slope;
  outside that, decimation is biased and entire id prefixes vanish.
  *Trip:* periodic CI run of `_selfcheck_powerlaw` on production id
  distribution.
- **ALWAYS_VISIBLE cardinality grows.** Currently ~10 kinds with O(domains+tools+files)
  membership. If `file` count crosses ~10⁵, the "always emit files"
  rule alone exceeds the per-frame budget — files must move into
  `_DECIMATED` or `_FAR_REDUCED`.
- **Importance-weighted queries.** When the user starts asking "show
  me the symbols that *matter*" (e.g. error sites, hot paths),
  uniform decimation is no longer satisficing — bias the hash by
  pre-computed importance, or move to a top-k oracle.

### S2 — Priority drops in scheduler (`_scheduler.QUEUE_SIZES`, line 78)

**Decision.** P0–P6 with caps {1k, 1k, 16k, 32k, 64k, 128k, 100}. Strict
priority pop; producer never blocks; full queue → drop+counter.

**Why it satisfices.** Optimal (never drop, elastic workers) is
intractable under 8 MB target / 19.4 MB worst-case (Dijkstra B1).
Dropping P5 first is good enough: 90%-edge graphs still communicate
topology; 90%-node graphs do not.

**Threshold beyond which "good enough" fails.**
- **P5 drop rate > ~10%.** The renderer is showing structurally
  misleading topology (clusters appear disconnected). *Trip:*
  `is_overloaded()` already exposes this; surface as a banner.
- **P4 (symbol) drops happen at all in steady state.** Symbol drops
  mean the user clicks a file, expects to see all its symbols, and
  some are missing without explanation. Caller must distinguish
  "burst absorption" from "sustained shedding" — sustained P4 drops
  break the contract.
- **Edge semantics become load-bearing.** When a downstream pipeline
  (impact analysis, dep graph) needs *every* edge, P5 dropping is no
  longer satisficing. Promote edges to P3, OR introduce an
  `add_edge_strict` path with backpressure.
- **P0/P1 drops > 0, ever.** Domain or tool_hub drops orphan entire
  subtrees. Must be a fatal alarm, not a counter.

### S3 — 1-decimal float precision in wire (`_wire.format_slot`, line 110)

**Decision.** `f"{slot.x:.1f}|{slot.y:.1f}"` — 0.1 px resolution. Saves
3–4 B/event vs `repr(float)`.

**Why it satisfices.** Full IEEE-754 round-trip (~24 B/coord) is
wasteful: at FILE_R=220 px, 0.1 px is 1/2200 of placement radius —
sub-pixel. Human visual acuity is ~1 arc-minute (~1 screen px); 0.1 is
below that.

**Threshold beyond which "good enough" fails.**
- **Zoom level where 0.1 world-unit < 1 screen pixel.** At 10× zoom,
  0.1 px world becomes 1 px screen — adequate. At 100× zoom, 0.1 px
  world is 10 px screen — quantization visible. *Trip:* when client
  zoom > ~10×, switch wire format to `:.3f` (3 decimal) at cost of
  ~6 B/event.
- **Coordinate range exceeds ±10⁵.** With `:.1f` the printable form
  scales linearly; at x=1e5 the float renders as 7 chars instead of
  the 5–6 budgeted. Spiral anchors at golden angle stay within ±10³
  empirically — but if domain count crosses ~10⁵, recompute.
- **Animation/interpolation downstream.** The 0.1 quantization causes
  visible "stair-step" if the renderer interpolates between frames
  with sub-pixel precision elsewhere. Currently the design has no
  per-event motion — placement is one-shot — so the threshold is not
  tripped.

### S4 — 500k event log cap (`_log._EVENT_LOG_CAP`, line 42)

**Decision.** Ring buffer of 500_000 events ≈ 40 MB at ~80 B/event.
Replay window for SSE reconnects via `Last-Event-ID`.

**Why it satisfices.** Persist-forever is 80 GB/stream — intractable.
Reconnect latency under network blips is 1–30 s; at 10⁴/s emit, 500k =
50 s of replay. Covers the practical reconnect distribution.

**Threshold beyond which "good enough" fails.**
- **`reconnect_latency × emit_rate > 500k`.** At sustained 10⁵/s
  emission (numpy-vectorised path), 500k is 5 s — narrower than a
  WiFi handoff. *Trip:* expose `replay_window_seconds` in stats; if
  observed reconnect lag exceeds it, clients silently lose events.
  Mitigation: snapshot-then-replay (client requests current state
  via REST, then resumes SSE from latest seq).
- **Multiple subscribers fall behind asymmetrically.** Slow subscriber
  triggers reap (Dijkstra §B3); but if reap is misconfigured, queues
  bloat and 500k log cap stops being the binding constraint —
  per-subscriber queues become the OOM source.
- **Long-haul disconnects (laptop sleep, mobile).** A user's laptop
  closed for 10 minutes returns to a stream that has rotated 6 M
  events past their Last-Event-ID. The contract silently degrades
  to "you missed 5.5 M events" — the client cannot tell. Surface
  `gap_detected: true` in the resume response.

## 3. Stopping rules — what "good enough" means here

For each tradeoff above, the satisficing criterion is **explicit**:

| Tradeoff | Aspiration | Stop-search trigger |
|---|---|---|
| LOD stride | uniform within ±5%, reconnect-stable | log-log slope ∈ [−1.05, −0.95] |
| P5 drop | edges 90%+ rendered | sustained drop rate < 10% |
| Float `:.1f` | sub-pixel at canonical zoom | 0.1 world < 1 screen px |
| 500k log | covers 95th-percentile reconnect | replay_seconds ≥ p95_disconnect |

When any trigger fires, the design must **lower the aspiration or
switch strategy** — Simon's adjustment rule. Continuing to ship the
same heuristic past its breakpoint is no longer satisficing; it is
denial.

## 4. The meta-satisficing decision

The authority itself satisfices: "simplest scheme that scales to 10⁹?"
Closed-form spiral + shells + hash decimation is not optimal on any
visual metric. It is good enough because the aspiration is "render at
all" and this is the only known path crossing that threshold under
budget. Waiting for "the right algorithm" is the trap Simon warns
against. Define threshold, search until crossed, ship.

## 5. Hand-offs

- **Curie** — measure actual reconnect-latency distribution, P5 drop
  rate under production load, and per-event ns budget at N=10⁶/10⁸.
  Verify each S1–S4 trigger is instrumented.
- **Hamilton** — when S2 thresholds trip (P0/P1 drops, sustained P4
  drops), surface as backpressure to the producer, not a counter.
- **Lamport** — formalize the S4 reconnect contract: "client resuming
  from seq=K within (now − replay_window) sees exact sequence;
  outside, sees gap_detected and snapshots". TLA+ if desired.
- **Engineer** — add the four trip-wires (slope check, drop-rate
  alarm, zoom-aware float precision, replay_seconds gauge) before
  any of S1–S4 reach production scale.
