# Thompson — Scaling-Law Audit of the Layout Authority

> "What works at insect scale collapses at elephant scale, not because the
> design is wrong but because the scaling laws forbid it." Map every cap,
> queue, and per-event byte count against N. Find where each ratio diverges.

## 1. Modules audited

| # | Module | Role | Dominant resource |
|---|---|---|---|
| 1 | `layout_authority_geometry.py` | Closed-form O(1) slot math | CPU cycles per slot |
| 2 | `layout_authority_protocol.py` | Contract-only dataclasses, invariants | none (declarative) |
| 3 | `layout_authority_scheduler.py` | Priority-displaced multi-queue | RAM (queue caps), shed rate |
| 4 | `layout_authority_log.py` | Append-only event log + fan-out | Ring buffer cap, subscriber queue |
| 5 | `layout_authority_wire.py` | SSE pipe-encoded bytes | bytes/event, encoder ns/event |

Plus `cost-model.md` (Carnot): per-node budget 1 ns at 1e9 / 1 s, working
set ≤ 8 MB. No `audits/fermi.md` exists.

## 2. Scaling table — what saturates first at each N

Rows = scale; columns = first failure. "First" = lowest N at which the
named cap is mathematically exceeded under the documented constants.

| N | Geometry | Scheduler P4 (symbols) | Scheduler P5 (edges) | Log ring (500k) | Subscriber queue (100k) | Wire bytes total | Wire encoder (ns/event) | First failure |
|---|---|---|---|---|---|---|---|---|
| 1e5 | 18-30 ms (1 core, py) | 64k cap, ~70k symbols → first drops on burst | 128k cap, ~400k edges → drops above 32% mark | 500k ≥ N ok | 100k ≥ N ok | ~8 MB | ~30 ms format | **scheduler P5 edges** (cap < typical 4×N edge fan-out) |
| 1e6 | 180-300 ms | catastrophic shed: 64k cap vs 1e6 symbols → ≥94% drops sustained | 128k vs ~4e6 edges → ≥97% drops | 500k < 1e6: **ring-buffer wraps; replay dies for any client > 0.5s late** | 100k: any client < 10 MB/s read drops | ~80 MB total stream | ~300 ms (single thread) | **log ring buffer overflow + subscriber queue overflow** |
| 1e7 | 1.8-3.0 s (single core); needs numpy batch (~50 ms) | hopeless at current cap; would need P4 cap = 1e7 = 800 MB → blows 8 MB ceiling | same | ring wraps every 0.5 s of stream; `Last-Event-ID` resume permanently broken; clients always fall back to snapshot | 100k drained at ~10k evt/s = 10 s of headroom only | ~800 MB stream; wire single-thread encode ~3 s | encoder is the bottleneck on a single core (~300 ns/event in pure py) | **encoder throughput + scheduler RAM** |
| 1e8 | 18-30 s pure py → mandatory numpy/SIMD; even numpy ~3-5 s/core single-thread | scheduler design fundamentally broken: all kinds beyond P0/P1 must shed >99% | same | log + replay model meaningless; must be replaced by a **server-side tile/quadtree snapshot** instead of streaming every slot | individual subscribers cannot read 8 GB/s; SSE per-client unicast unsustainable | ~8 GB stream per subscriber; 1 Gbit/s LAN = 80 s wire time minimum | encoder must move to C/Cython or batched numpy `tobytes` (~30 ns/event) | **network bandwidth + per-client unicast model** |
| 1e9 | 1-2 s only with numpy batch + multi-core (~5-8× on 8 cores) | meaningless to enqueue per-slot; must batch-emit by domain shard | same | streaming individual slot events is impossible: at 82 B × 1e9 = **82 GB per client**. Must be precomputed tiles | 100k cap drains in ~10 ms at any plausible rate | ~82 GB/client unicast; **10 Gbit LAN = 65 s; 1 Gbit = 11 min** | encoder ns budget: 82 GB / 2 s = 41 GB/s — exceeds DRAM single-thread bandwidth | **transport (network + per-client unicast) and storage representation; the per-event SSE model is geometrically impossible** |

## 3. Per-module break analysis (form vs scale)

### Geometry — survives the longest by design

Cost-model says ~180-300 ns/slot pure Python; ~10 ns/slot needed at 1e9.
Geometry is the **only** module that scales O(1) per node and bounded
state O(domains × kinds). Break point isn't the algorithm — it's the
Python interpreter loop. Mitigation already named in cost-model: numpy
vectorization at 1e7+; multi-core fan at 1e9. **Form survives all five
scale steps; only the substrate (Python → numpy → C) changes.**

### Scheduler — breaks at 1e6, irrecoverable at 1e7

Priority caps (P4=64k symbols, P5=128k edges) are sized for one specific
scale: ~1e5 visible at peak. The shed-low-priority pattern (Hamilton
1969) **works as designed** through 1e5. At 1e6 the symbol stream sheds
>94% sustained; that is no longer "graceful degradation" — that is data
loss as the steady state. RAM blows the 8 MB ceiling if caps are raised:
P4 cap = 1e7 × 80 B = 800 MB. **The form (single in-process scheduler)
is forced to change at 1e7.** Mitigation: shard the scheduler per domain
(11 schedulers, each handles ~N/11 slots) OR move scheduling out of the
authority entirely and let the build worker emit pre-bucketed tiles.

### Log ring buffer — breaks at 1e6

Cap 500k events at ~80 B = 40 MB (already 5× over the 8 MB working-set
ceiling — flagged in the module docstring as a deliberate exception).
At N = 1e6 the ring wraps in less than the round-trip of a slow client,
so `Last-Event-ID` resume **permanently fails** and every reconnect
falls back to a snapshot — which itself must be the size of the full
graph, which we just said is geometrically impossible to serialize.
**The form (linear append-only log replayable by seq) cannot survive
1e7+. Mitigation: per-domain logs or, more honestly, abandon replay and
serve a snapshot from a server-side spatial index.**

### Subscriber queue (100k cap) — breaks at 1e6

A subscriber drained at 10k events/s holds 10 s of headroom. At 1e6
total stream events delivered in any practical wallclock the queue will
fill within seconds for any subscriber that does any per-event work
(parse + render). 200-miss eviction kicks in. **Form (per-client
unicast queue) breaks at 1e6 for slow clients, at 1e7 for any client
that isn't a localhost socket.** Mitigation: drop unicast SSE in favor
of a shared in-memory ring readable by all clients via mmap, or a
broadcast multicast channel — both are different forms.

### Wire (SSE pipe encoder) — breaks at 1e7-1e8

Encoder is ~300 ns/event pure Python (extrapolated from a 1M slot
benchmark hook). At 1e7 single-threaded encode ≈ 3 s; at 1e8 ≈ 30 s.
Bytes per event are H-bounded (~82 B for the chosen pipe format — a
~4× win over JSON, but still O(N) wire bytes). At 1e9 the **bytes
themselves** (82 GB) exceed DRAM bandwidth on a single thread (~50 GB/s)
and exceed any plausible network. **Form (per-event SSE frame) cannot
survive 1e8 without a transport change.** Mitigation: batched `bytearray`
encoder in C/Cython at 1e7; protobuf/cap'n proto with delta compression
at 1e8; **at 1e9, drop streaming entirely and serve PNG/Datashader tiles
or quadtree pyramids** — the form is forced.

### Protocol — survives everything

Contract module. Has no resources to saturate. Invariants I3/I4/I5 (the
pending-edges buffer at 100k, parent-before-child ordering, no
retroactive reseat) keep their semantics across all scales but enforcement
moves from in-process to a sharded model at 1e7+.

## 4. Where the design fundamentally needs a different architecture

The current authority is a **single-process, single-producer, per-event
streaming** design. Its scaling envelope is hard-bounded by:

- **1e5 nodes** — current architecture is correct and roomy. Scheduler
  caps designed exactly here.
- **1e6 nodes** — log ring + subscriber queue + scheduler P4/P5 all
  break first. Mitigation is parameter tuning (raise caps within RAM)
  plus a numpy batch path in the geometry. **Same form, retuned.**
- **1e7 nodes** — single-process becomes structurally inadequate. RAM
  for queue caps blows 8 MB. Encoder single-thread blows 1-2 s budget.
  **Form change required: per-domain sharding (11 worker processes,
  each owns a domain's counters + scheduler + log) — same Hamilton
  pattern replicated, not redesigned.**
- **1e8 nodes** — per-client unicast SSE is geometrically impossible.
  **Form change required: server-side spatial index (quadtree) +
  pre-rendered tile pyramid; client requests viewport tiles instead of
  individual slots.** This is exactly the Datashader/server-tile path
  already in repo (`server-tile + Datashader path for >1M-node graphs`,
  commit dba2f16).
- **1e9 nodes** — single-machine is over. Bytes-per-event is the
  binding constraint. **Form change required: distributed compute
  (1 process per domain shard, each on its own core; GPU rasterization
  for tile generation; CDN-cached tile delivery).** Streaming individual
  slots ceases to be the operational model — the renderer asks for
  zoom-level-k tiles and the authority precomputes them by batch numpy
  + CUDA.

## 5. Hand-offs

- **Fermi**: empirical measurement of subscriber drain rate, encoder
  ns/event in production CPython 3.14, and ring-buffer wrap latency at
  N = 1e6 (currently extrapolated, not measured).
- **Curie**: confirm the 10 ns/slot extrapolation in cost-model holds
  with a numpy batch path; measure end-to-end at N = 1e7.
- **Hamilton**: design the sharding boundary at 1e6 → 1e7 transition
  (per-domain authority instances) and the SSE backpressure path so
  slow subscribers fall back to tile snapshots cleanly.
- **Coase**: when the form shifts to distributed compute at 1e9, the
  organizational boundary (which team owns the tile pipeline vs the
  authority?) needs explicit assignment.
