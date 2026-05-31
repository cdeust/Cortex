# Ekman observable-signal audit — Layout Authority

**Procedure.** Treat "is the authority healthy?" as a domain currently
read by holistic impression. Convert it into an objective coding
system: enumerate the smallest observable signals (FACS-style atoms),
anchor each to a code path, classify each as load-bearing or noise,
and build a signal → symptom mapping two on-call operators converge on.

Files audited: `layout_authority.py`, `_log.py`, `_scheduler.py`,
`_protocol.py`, `_wire.py`, `_lod.py`, `ui/unified/js/streaming_canvas.js`.

---

## 1. Codebook — atomic observable signals (the AUs)

Each row is one independently-variable signal. "Anchor" = the exact
producer; "Resolution" = the temporal grain at which the signal is
present (Move 2 — leakage is in the small window).

| # | Signal | Anchor (producer) | Resolution | Class |
|---|---|---|---|---|
| S1 | SSE event `kind == "slot"` | `_log.emit("slot", …)` `layout_authority.py:359` | per node | load-bearing |
| S2 | SSE event `kind == "edge"` | `_log.emit("edge", …)` `layout_authority.py:369` | per edge | load-bearing |
| S3 | SSE event `kind == "done"` | `_log.emit("done", …)` `layout_authority.py:226` | per build | load-bearing (terminal) |
| S4 | SSE sentinel `replay_lost` | SSE handler in `graph_stream` (`_log.py:170` doc) | per reconnect | load-bearing |
| S5 | `_event_log_drops` counter | `_log.py:54,134` | per dropped event | load-bearing |
| S6 | `_dead_subscribers` count via `stats()` | `_log.py:_fan_out` (200-miss threshold) | per dead consumer | load-bearing |
| S7 | Per-priority `Stats.dropped[p]` | `_scheduler.py:179,196` | per dropped delta | load-bearing (P0/P1 only) |
| S8 | Per-priority `Stats.queued[p]` | `_scheduler.py:182,199` | per submit | noise (cumulative; counter only) |
| S9 | Current queue length per priority | `_scheduler.py:242` | per `stats()` poll | load-bearing (saturation) |
| S10 | `Scheduler.is_overloaded(0.8)` | `_scheduler.py:253` | per poll | load-bearing |
| S11 | `slots_emitted` / `edges_emitted` totals | `layout_authority.py:167–168` | per build | noise (rate-derivable from S1/S2) |
| S12 | Protocol violation `ValueError` | `layout_authority.py:128–132` | per bad delta | load-bearing |
| S13 | `_log` peek-vs-actual seq assert | `layout_authority.py:360` | per emit | load-bearing (invariant breach) |
| S14 | Subscriber `put_nowait` miss streak | `_log.py:_fan_out` 0…200 | per fan-out | noise individually; load-bearing as streak |
| S15 | LOD `_selfcheck_powerlaw` slope drift | `_lod.py:190` ±0.05 of −1.0 | per build sample | load-bearing |
| S16 | SSE keepalive `: ping\n\n` | wire layer | per 15 s | NOISE (transport-only) |
| S17 | Log oldest/newest seq gap | `_log.stats()` | per poll | load-bearing (replay window depth) |
| S18 | `replay_since` returns `None` | `_log.py:174` | per reconnect | load-bearing (precedes S4) |

Independence (Move 1): S1/S2/S3 mutually exclusive kinds. S5 (log
ring overflow, post-emit) and S7 (scheduler drops, pre-emit) measure
*different layers* — not redundant. S14 aggregates into S6.

---

## 2. Baseline — what "healthy" looks like (Move 3)

Report **deviation from baseline**, not absolute thresholds. Targets
below are calibration slots, not invented constants.

| Signal | Baseline | Source |
|---|---|---|
| S1 rate | matches scheduler drain rate steady-state | Curie §3.4 |
| S3 latency | one `done`/build within (wall × 1.05) | e2e bench |
| S4, S5, S6, S12, S13 | 0 | structural / invariant |
| S7 P0/P1 | 0 | invariant — never drop hubs |
| S7 P2..P5 | ≤0.1 % of S8 at same priority | saturation bench |
| S9 length | < 0.5 cap p50, < 0.8 cap p99 | `_scheduler.py:78–86` |
| S10 | False at p99 over 60 s | poll loop |
| S14 streak | < 5 per healthy-but-slow consumer | Curie §3.4 |
| S15 slope | ±0.05 of −1.0 on production ids | `_selfcheck_powerlaw` |
| S17 | client `last_event_id` ≥ oldest_seq | `replay_since` precondition |

---

## 3. Signal → symptom mapping (two-coder agreement target)

Each row is the form: **observed deviation → classified state → action**.
Designed so a second operator, given only the signals, reaches the
same classification.

| Observed deviation | State | Diagnosis | Action |
|---|---|---|---|
| All S1..S3 absent for >2 s after build start | **broken** | producer thread stalled or never started | inspect authority worker; check S12 |
| S3 never arrives, S1 rate >0 | **degraded** | build never seals; scheduler drain ≠ producer | check S9 high-priority lengths |
| S5 > 0 (single event) | **degraded** | event log ring overflow; some consumer is replaying impossibly old | check S6, S17; client should resync via S4 |
| S4 fired on a client | **degraded for that client** | client `last_event_id` < oldest_seq; gap > replay window | client snapshot-resync (designed path) |
| S6 ≥ 1 (dead subscriber) | **degraded** | one consumer crossed 200-miss streak (S14) | drop confirmed; investigate that consumer |
| S7[P0] > 0 or S7[P1] > 0 | **broken** | invariant violation: domain/tool hubs MUST NOT drop | scheduler caps wrong or producer overrunning P0/P1 |
| S7[P2..P5] > baseline | **degraded** | sustained backpressure; LOD will mask but signal real | shed lower priority before higher; verify S10 |
| S9[p] ≥ 0.8 cap sustained | **degraded** | scheduler saturated at priority p | S10 should already report True; if not, polling stale |
| S10 True for > 60 s | **degraded** | system not draining | check downstream SSE consumer; cf Pearl audit |
| S12 ≥ 1 | **broken** (producer bug) | malformed delta from caller | reject + log; do not heal silently |
| S13 assert fires | **broken** (invariant breach) | multi-producer to `_log.emit` | crash; do not continue — seq monotonicity gone |
| S15 \|slope+1.0\| > 0.05 | **degraded** (LOD) | hash distribution skewed on real ids | re-calibrate stride; cf Curie C22 |
| S17 gap shrinking faster than S1 rate | **degraded** | replay window collapsing; future S4 likely | enlarge `_EVENT_LOG_CAP` or shed |
| Only S16 (keepalives) on stream | **healthy idle** | no work in flight | none |

Two-coder calibration (Move 6): give two operators the same 60 s
`stats()` trace + SSE tap. Cohen's κ on {healthy, degraded, broken}
must exceed 0.8 before this codebook is declared usable.

---

## 4. Micro-temporal leakage (Move 2)

`stats()` polls at 1 Hz hide signals living below 1 s:

- **Burst drop on S7[P5]**: 50 ms window where edges burst past 128 k
  cap, dropped, queue drains. Invisible at 1 Hz. → Histogram with
  10 ms buckets, or per-emit dropped-counter delta.
- **Subscriber miss-streak (S14 → S6)**: 200 misses × ~1 ms = 200 ms
  window. S6 fires only *after* death; the streak is the leading
  indicator. → Expose `max_current_miss_streak` in `stats()`.
- **`done` arrival jitter**: smoothed mean hides 2-of-100 stalls. →
  Per-build histogram, not running mean.
- **S13 peek-vs-actual race**: passes silently 99.999 % of the time;
  the one frame it fires IS the multi-producer breach. Crash on
  assert is correct — there is no slower signal that captures it.

---

## 5. Cross-context calibration (Move 4)

| Context A | Context B | Survives? |
|---|---|---|
| 1k-node smoke | 10⁸-node prod | S1..S3 invariant; S7[P5] threshold local |
| 1 SSE consumer | 10 concurrent | S6/S14 only surface with N≥2 |
| Local net | Cross-region | S14 baseline shifts; cap stays |
| Fast disk | Throttled disk | drain baseline shifts; deviation logic survives |

Universal: S1/S2/S3 protocol, S4 sentinel, S12/S13 invariants. Local
(display rules): exact thresholds for S9/S14/S17 — calibrate per
deployment. AUs universal; caps cultural.

---

## 6. Coverage boundary (what this codebook CANNOT code)

- **Renderer correctness** — slots emit OK but visually wrong. Pixel
  golden test (Curie §3.5).
- **Geometry quality** — clumping, sector overflow not coded here.
- **End-to-end latency caller→paint** — network + renderer out of scope
  (Hamilton, transport).
- **Memory residency** (RSS/heap) — no byte-level signal here (Curie
  C4/C13/C18).
- **"Why is the consumer slow"** — Pearl, not Ekman.

A green dashboard on this codebook ≠ system correct; only healthy in
the coded dimensions.

---

## 7. Refusal markers

- Any operator claim of "authority is degraded" without naming one of
  S1–S18 with a deviation from §2 baseline → reject; no signal, no
  state.
- Any new metric added to `stats()` without classification (load-
  bearing vs. noise) and a baseline → refuse; uncoded metrics
  inflate the dashboard and reduce inter-operator agreement.
- S5/S7[P0]/S7[P1]/S12/S13 ≠ 0 must page; they are invariant
  breaches, not gradients.

---

## 8. Hand-offs

- **Inter-operator κ ≥ 0.8 calibration run** → engineer agent (build
  the trace fixture, run two-coder labelling on §3 table).
- **Histogram exposure for S7[P5] burst, S14 streak, S3 jitter** →
  engineer agent (extend `Scheduler.stats()` and `_log.stats()`).
- **Why does the SSE consumer slow down (S10 sustained True)?** →
  Pearl (causal-graph audit of consumer pipeline).
- **Pixel/geometry correctness (coverage gap)** → Curie §3.5
  golden-test follow-up.
- **Replay-window cap calibration (S17/S4)** → Curie §3.3 (already
  named: 95th percentile of reconnect-window).

---

## 9. Verdict

18 signals: 3 noise (S8, S11, S16), 15 load-bearing. Five (S5, S7[P0],
S7[P1], S12, S13) are invariant breaches that must page; rest are
gradients requiring baseline + cross-context calibration. The code
emits the right atoms; what was missing is this codebook plus the
trained-coder agreement protocol (§3 κ ≥ 0.8 target).
