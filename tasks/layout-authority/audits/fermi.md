# Fermi audit — layout authority thresholds

Bracket every constant to within an order of magnitude. One-line defense per constant: WHY this magnitude, what next-up costs, what next-down costs. Bracket = [low, high] interpreted as the range over which the constant remains operationally correct; anything outside breaks something concrete.

## `layout_authority_geometry.py` — radii and sectors

Anchors: a Cortex graph viewport is ~1280×800 px (10^3 px). A node glyph reads at ~10 px (10^1). Therefore radii should live in 10^1..10^3 px; the only question is the ratio of one shell to the next.

| Const | Value | Bracket | One-line defense |
|---|---|---|---|
| `SETUP_R` | 70 | [50, 100] | Inside file shell; ×10 down (7 px) collides with domain glyph; ×10 up (700 px) crosses into other domains. |
| `TOOL_R` | 140 | [100, 200] | 2× setup so tool hubs visibly own a ring; ×0.1 = 14 px overlaps domain dot; ×10 = 1400 px exceeds canvas. |
| `FILE_R` | 220 | [150, 300] | 1.5× tool ring leaves room for file glyph + label; ×0.1 puts files inside tools (semantic inversion); ×10 escapes viewport. |
| `DISC_R` | 150 | [100, 250] | Side lane between tool and file rings; same magnitude argument. |
| `MEM_R` | 150 | [100, 250] | Mirror of DISC_R on the opposite side. |
| `MCP_R` | 50 | [30, 80] | Inward of domain hub; ×10 down (5 px) is invisible; ×10 up (500 px) puts MCPs in the next domain's territory. |
| `SYM_R_OUTER` | 290 | [220, 400] | Just outside FILE_R so symbols visually orbit their file; ×0.1 collapses into file; ×10 unmoors symbols from parent. |
| `SYM_R_SPREAD` | 32 | [16, 64] | Symbol scatter around file center; ×10 down indistinguishable; ×10 up overlaps neighbour file. |
| `SYM_CLUMP_R` | 18 | [10, 32] | Petal cluster radius; ×10 down hides symbols, ×10 up crosses into adjacent file petal. |
| `SECTOR_SETUP_HALF` | π/2.6 ≈ 69° | [45°, 90°] | Front sector for L1 fan; ×10 down (~7°) crowds skills/hooks/commands/agents into a stripe; ×10 up wraps the ring. |
| `SECTOR_SIDE_HALF` | π/6.5 ≈ 28° | [15°, 45°] | Side lane half-angle; ×10 down collapses lane to a line; ×10 up overlaps front sector. |
| `SECTOR_SIDE_ANGLE` | 0.72π ≈ 130° | [90°, 150°] | Lane offset from outward; bracket fixed by geometry — must be > setup_half + side_half (~97°) to avoid overlap, < 180° to stay non-symmetric. |

All radii are *copies* from `ui/unified/js/workflow_graph.js`; the source-of-truth bracket is "whatever the JS already shipped that users approved" — Move 2 anchor. Order-of-magnitude sanity: 10× any of them and the layout escapes the canvas; 0.1× and shells fuse.

## `layout_authority_scheduler.py` — queue caps and priorities

Anchors. A NodeDelta/EdgeDelta is ~80 B (pointer + small dataclass). Sustained drain rate at a single producer thread doing closed-form O(1) slot math: ~10^5 items/sec (Move 2 — Python attribute access ~100 ns, dict lookup ~50 ns, deque.append ~50 ns). Therefore queues only have to absorb *bursts*, not steady-state.

| Const | Value | Bracket | Defense |
|---|---|---|---|
| `QUEUE_SIZES[0]` (P0 domain) | 1 000 | [100, 10 000] | Population is ~10^1 in practice; cap is 100× over so it cannot drop. ×10 down (100) is still 10× population — fine. ×10 up (10k) wastes 800 KB. |
| `QUEUE_SIZES[1]` (P1 tool_hub) | 1 000 | [100, 10 000] | Population ~70; same argument. |
| `QUEUE_SIZES[2]` (P2 file) | 16 000 | [4k, 64k] | Files in a typical Cortex graph: ~30k. Cap < population by design — drops above are explicit, scheduler's job is burst absorb not full storage. ×10 down (1.6k) drops most files. ×10 up (160k × 80 B = 13 MB) breaks 8 MB ceiling. |
| `QUEUE_SIZES[3]` (P3 setup/disc/mem) | 32 000 | [10k, 100k] | Mid-volume mid-importance kinds. Same memory ceiling argument up; ×10 down would drop healthy session loads. |
| `QUEUE_SIZES[4]` (P4 symbol) | 64 000 | [16k, 256k] | "~90% of symbols visible is fine" per docstring; symbol population at 10^9 nodes is dominated by this priority. Naive 500k cap = 40 MB busts ceiling (already documented in module). ×10 down (6.4k) loses too many symbols visibly; ×10 up (640k × 80 B = 51 MB) blows budget. |
| `QUEUE_SIZES[5]` (P5 edge) | 128 000 | [32k, 512k] | Edges typically 4× nodes; cap is 2× P4 so the 4:1 ratio survives a burst. ×10 up = 10 MB just for edges. ×10 down loses too many edges to keep topology readable. |
| `QUEUE_SIZES[6]` (P6 subtree) | 100 | [10, 1 000] | Coalesced; even a viewport-drag at 10 req/s × 10 s = 100. ×10 down (10) drops legitimate user requests; ×10 up (1k) is 80 KB — wasted but harmless; coalescence keeps real depth at O(domains) = ~10. |

Total worst-case memory ≈ 19 MB (per docstring). Bracket [8 MB, 50 MB]: 8 MB target is the project ceiling; 50 MB is where Python overhead alone (interpreter + numpy + libs at ~150 MB RSS) makes this allocation negligible. Sustained residency is 1–2 orders below.

## `layout_authority_log.py` — event log + subscriber thresholds

| Const | Value | Bracket | Defense |
|---|---|---|---|
| `_EVENT_LOG_CAP` | 500 000 | [100k, 1M] | At ~80–112 B/event (tuple overhead + payload), 500k × 112 B ≈ 56 MB — already documented as exceeding 8 MB ceiling on principle. ×10 down (50k events ≈ 5–6 MB) restricts replay window to ~5–50 s of stream which would force snapshot-fallback for any client hiccup. ×10 up (5M ≈ 560 MB) is process-OOM territory. Bracketed range is "client survives a 30 s tab-switch but server stays under 100 MB". |
| `_SUBSCRIBER_QUEUE_CAP` | 100 000 | [10k, 1M] | One slow subscriber × 100k × ~112 B ≈ 11 MB. ×10 down means a subscriber 1 s behind at 10^4 evt/s gets reaped; ×10 up means a single dead client can hold 110 MB. Current value tolerates ~10 s lag at 10^4 evt/s. |
| `_DEAD_QUEUE_MISS_THRESHOLD` | 200 | [50, 1 000] | 200 consecutive failed `put_nowait` ≈ 200 events = ~20 ms at 10^4 evt/s. ×10 down (20) reaps a momentarily slow but recoverable client; ×10 up (2k) lets a dead client hold its 11 MB queue for ~200 ms longer. The cost asymmetry favours the current value. |

## `layout_authority_wire.py` — encoder constants

| Const | Value | Bracket | Defense |
|---|---|---|---|
| `_MAX_KIND` | 32 chars | [8, 128] | Identifier ceiling per CLAUDE.md. ×10 down (3) cuts off real kind names like `tool_hub`; ×10 up (320) admits abuse-vector long strings that bloat every event by 10×. ASCII-identifier convention pegs this. |
| Float fmt `:.1f` | 1 decimal | [0, 2 decimals] | At FILE_R = 220 px, sub-pixel precision is invisible. 0 decimals saves ~3 B but loses snap-to-grid feel; 2 decimals adds ~3 B/coord = ~6 B/event = 6% bloat at no visible benefit. |

There is no explicit chunk-size constant in `_wire.py` — the encoder returns finished `bytes` per event and the SSE handler writes directly. Implicit chunk size = one event ≈ 80–110 B. Bracket [50 B, 4 KB]: smaller than 50 B is below TCP-segment-overhead efficiency threshold; bigger than 4 KB delays first-byte for downstream parser.

## Realistic peak event rate

Decompose: Rate = (Producer throughput) × (channel capacity gate) × (consumer parse rate).

| Factor | Low | High | Anchor |
|---|---|---|---|
| Producer (Python deque + closed-form geometry) | 3×10^5 evt/s | 1×10^6 evt/s | Module benchmark `_benchmark` claims ~250 ns/event ≈ 4×10^6 evt/s for encoding alone; submission + lock + fan-out ~1 µs realistically. |
| SSE-over-localhost channel | 10^4 evt/s | 10^5 evt/s | Given anchor in the prompt. |
| Browser parse + render | 10^4 evt/s | 10^5 evt/s | `String.split('|')` ~250 ns; render upper-bounds at 60 fps × ~10^3 nodes/frame batch = 6×10^4 evt/s. |

Bottleneck = SSE channel ∩ browser parse. **Realistic peak ≈ 3×10^4–10^5 evt/s.** Dominant uncertainty: whether the Datashader/tile pipeline batches events into render frames (raises ceiling toward 10^5) or renders per-event (caps at ~10^4).

## Bracket: full build + stream at 10^9 nodes

Decompose. Total wall time = max(build_compute, stream_throughput, render_throughput).

| Factor | Low | High | Notes |
|---|---|---|---|
| Build compute @ ~10^6 slots/s closed-form | 10^3 s | 10^4 s | 10^9 / 10^6 = 1000 s; Python overhead and GC may cost 10×. |
| Stream wire bandwidth | 2×10^4 s | 10^5 s | 10^9 events × 100 B = 10^11 B = 100 GB; over 1 GB/s loopback = 100 s; over realistic 10–100 MB/s SSE = 10^3–10^4 s. |
| Browser render at 10^4–10^5 evt/s | 10^4 s | 10^5 s | This is the binding constraint. |
| Edges (typically 4× nodes) | ×4 | ×4 | Multiplies all of above. |

**Bracket: 10^4 s–10^5 s ≈ 3 hours to 30 hours for nodes alone, ×4 with edges → 10–100 hours.**

Cross-check (independent decomposition): at 10^9 nodes the event log cap (500k) holds ~5 ms of stream — therefore *no client* can replay; full re-stream from cache is the only path, confirming the system is not designed for live 10^9-node streaming. Either build is offline + tile-served (current direction per `tasks/tile-server-plan.md`) or the renderer drops to aggregate tiles (current `unified-viz.html` Datashader path).

## Dominant uncertainty

The widest bracket is **browser render throughput** (10^4–10^5 evt/s, ×10 spread). Every other factor is either cheaper (Python compute) or already mitigated (server-side tiling). Move 5: refine *only* this bracket — instrument actual sustained event-application rate in the existing tilemap renderer at 10^6 nodes and extrapolate. That single measurement collapses the 10–100 hour bracket to a 2× spread.

## Model assumptions (estimate invalid if any change)

- Single-producer thread (Hamilton invariant in `_log.py` docstring).
- Closed-form O(1) slot math (no graph layout iteration).
- Localhost SSE (cross-network would cap at 10^3–10^4 evt/s).
- Browser is the consumer (a headless tiler could push render to 10^6+ evt/s).
- Node payload ~80 B; doubling payload doubles all wire-bound estimates.

## Next measurement (hand off to Curie)

Instrument browser render apply-rate on the current tilemap path at 10^5, 10^6, 10^7 nodes. The slope determines whether 10^9 is a 10-hour or a 100-hour build.
