# Knuth audit — layout authority benchmark, profile-before-optimize

**Discipline:** Knuth (1974), *Computing Surveys* 6(4), 261–301. The
agent's job here is to **measure**, not to speculate. The numbers below
are reproducible from the harness at
`mcp_server/server/bench_layout_authority.py`.

## How to reproduce

```bash
python3 -m mcp_server.server.bench_layout_authority           # N=1M (default)
python3 -m mcp_server.server.bench_layout_authority --n 50000 # smoke test
```

## Environment

- Hardware: Apple M4
- OS: Darwin 25.4.0 (xnu-12377)
- Python: 3.14.4 (CPython, no JIT flag, single-threaded harness)
- Git HEAD: `4a41aff` (`fix(viz): tilemap auto-recovers ...`)

## Workload

| Kind        | Count   |
|-------------|---------|
| domains     | 10      |
| tool_hubs   | 70      |
| files       | 30,000  |
| symbols     | 250,000 |
| memories    | 250,000 |
| entities    | 100,000 |
| discussions | 50,000  |
| padding (skill/hook/command/agent/mcp round-robin) | 319,920 |
| **total nodes** | **1,000,000** |
| **edges (4×N)** | **4,000,000** |

## Measured results (N = 1,000,000, two consecutive runs)

| Bench | n     | run 1 (ns/op) | run 2 (ns/op) | ops/sec (run 2) |
|-------|-------|---------------|---------------|-----------------|
| `geometry.compute_slot`       | 1,000,000 | 440.3 | 436.9 | 2,288,949 |
| `scheduler.submit+pop`        | 5,000,000 | 155.1 | 154.2 | 6,486,465 |
| `log.emit+replay_since`       | 1,000,000 | 265.0 | 267.0 | 3,745,200 |
| `pipeline.scheduler+log+wire` (integration) | 5,000,000 | 1,467.8 | 1,373.5 | 728,073 |

Variance run-to-run is < 7% on every component and < 7% on integration —
the harness is stable enough to trust the relative ranking.

## Bottleneck (component, the 3% in Knuth's sense)

**Component bottleneck: `geometry.compute_slot` at 437 ns/op.**

Of the three component micro-benchmarks, geometry is the most expensive
per node: ~437 ns/op vs ~155 ns for scheduler submit+pop and ~265 ns for
log emit. Across the full 1M nodes, that is **0.44 s of CPU time spent
inside the geometry dispatcher** — roughly 32% of the integration
budget. The dispatcher is a chain of `if/elif` on `node_kind` with dict
construction + lookup at every call site; the underlying trig functions
themselves are sub-100 ns each.

## Integration verdict

Integration runs at **~728 k events/sec** (pipeline submits a NodeDelta
or EdgeDelta, pops it, formats the SSE frame, and emits it to the log).
At 5M total events that's a ~6.8 s end-to-end run.

The integration's per-event cost (~1,400 ns) is not equal to the sum of
the component costs. Two reasons:

1. The integration runs in **batches of 4096 with intermediate drains**,
   so RAM stays bounded — but each drain pays Python-call overhead the
   straight-line components don't.
2. Edges (4× nodes) only pay the scheduler + log + `format_edge`
   path; they skip geometry entirely. The integration's per-event cost
   is therefore a weighted blend of node-path and edge-path.

## Surprising finding (the `replay_since` gap path)

The log uses a **500,000-event bounded ring buffer** (see
`layout_authority_log.py:42`) but `_event_seq` is **global and never
rewinds** (per invariant I3). When N nodes (or N + 4N events at
integration) exceeds the ring cap, **the baseline-seq captured before
the run drops out of the ring**, and `replay_since(baseline)` correctly
returns the gap signal `([], oldest_seq)`.

This is by-design: the SSE handler uses that gap to tell the client
"replay window lost, fall back to a snapshot." But it surprised the
benchmark — the harness now exercises that path explicitly at N=1M,
which is useful: integration-time at N=5M total events guarantees the
gap branch is hit, not the happy path. **At N ≤ 500k the happy path is
hit; at N > 500k the gap path is hit. Both are correct.**

## What NOT to optimize (the 97%, per Knuth)

- **`scheduler.submit+pop` (155 ns/op).** Already 2.8× faster than
  geometry and 1.7× faster than the log. Optimizing it cannot move the
  integration figure by more than a few percent.
- **`log.emit` itself (265 ns/op including replay).** Lock acquisition
  and deque-append are already near-optimal Python idioms.
- **The wire encoder** — `format_slot` was independently benchmarked in
  `layout_authority_wire.py::_benchmark` and clears 1M events/sec on
  CPython. Nothing here is the bottleneck.

## What MIGHT be worth optimizing (the 3%, per Knuth)

Only if there is a measured production need:

1. **`compute_slot` dispatcher.** The `if/elif` chain on `node_kind`
   plus dict-construction-per-call is the dominant cost. A flat
   per-kind callable lookup (e.g. `_DISPATCH = {"domain": _do_domain,
   ...}`) and passing `*args` instead of building a dict would likely
   shave ~100 ns/op. **Do not do this until production profiling shows
   the layout-authority worker is geometry-bound** — at 2.3M slots/sec
   the geometry already saturates a single core well above the live
   visualization's actual emission rate.
2. **The integration's batch-drain cadence (BATCH=4096).** The current
   drain is bounded but pays Python-call overhead at each batch
   boundary. Worth re-measuring after (1) lands, not before.

## What this audit deliberately does NOT do

- Does **not** propose a code change. The harness is the audit; the
  next agent decides whether the production target rate justifies the
  optimization cost.
- Does **not** speculate about CPython 3.14's JIT. Numbers above are
  with the default interpreter; if `--enable-experimental-jit` is in
  play in production, re-run before deciding.
- Does **not** measure GC pauses. The harness is short enough that GC
  contributes < 1% (verified by re-running with `gc.disable()` — same
  numbers within noise).

## Files touched

- `/Users/cdeust/Developments/Cortex/mcp_server/server/bench_layout_authority.py` — the harness (250 lines).
- `/Users/cdeust/Developments/Cortex/tasks/layout-authority/audits/knuth.md` — this report.
