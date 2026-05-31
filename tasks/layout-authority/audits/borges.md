# Borges Audit — Layout Authority Failure-Space

**Method.** Imagine the library of *all* execution traces for the chain
`add_node → scheduler → log → wire → SSE → client paint`. Enumerate the
failure modes a reasonable design must enumerate but typical engineering
dismisses as "won't happen." Compare the **map** (full failure space) with
the **territory** (what the modules actually handle).

**Sources audited.** `layout_authority_protocol.py`, `_scheduler.py`,
`_log.py`, `_wire.py`, `_lod.py`, `_geometry.py`, `handlers/quadtree_handler.py`,
`handlers/recompute_layout.py`, `server/http_standalone*.py`.

**Legend.** HANDLED · SILENTLY-DEGRADES · CRASHES · CORRUPTS.

---

## 1 — Producer side (build worker → authority)

| # | Failure mode | Status | Evidence / mechanism |
|---|---|---|---|
| 1.1 | Producer crashes mid-emit (between `add_node` and corresponding `add_edge`) | SILENTLY-DEGRADES | No transactional boundary around an emit pair. Pending-edges buffer (I5) tolerates orphaned source/target. No crash beacon emitted, so client cannot distinguish "still building" from "build dead." |
| 1.2 | Two builds racing (overlapping recomputes) | CORRUPTS | `recompute_layout.serve` is synchronous but has no mutex around `_graph_cache` or `layout_pg_store.write_layout`. Two concurrent POSTs interleave: same `topology_fingerprint`, two different `layout_version` rows; the SSE log's `_event_seq` is global, but `reset()` from build B wipes events still being drained by build A. |
| 1.3 | Producer single-thread invariant (log docstring) violated by accident | CORRUPTS | `emit()` is documented as single-producer but **not enforced**. Two threads incrementing `_event_seq` under the lock keeps seq monotonic, but the post-lock `_fan_out` runs unsynchronized — per-subscriber delivery order can disagree with seq, breaking I2. |
| 1.4 | `add_node` with NaN/inf coordinates produced upstream | HANDLED | `_validate_finite` in wire layer raises before write. |
| 1.5 | `add_node` with `kind` not in `NODE_KINDS` | HANDLED | Protocol contract raises ValueError. |
| 1.6 | `add_node` violates per-kind preconditions (`tool_hub` w/o `tool_name`, etc.) | HANDLED | Documented in `NodeDelta.Pre`; reference impl raises. |
| 1.7 | Edge whose endpoints never arrive (dangling forever) | SILENTLY-DEGRADES | I5 buffer at 100k. Beyond cap, oldest pending edges are dropped with a counter — but **counter is never surfaced** in `quadtree_handler` or `/api/layout/stats`. Client paints a graph with missing edges and no warning. |
| 1.8 | Producer emits 1e9 events at >1M ev/s | SILENTLY-DEGRADES | Wire layer benchmark targets ~1M ev/s; ring buffer caps replay at 500k. Sustained producer rates above subscriber drain rate cause subscriber eviction (200-miss threshold). The build "succeeds" but late subscribers see only the tail. |
| 1.9 | Scheduler P5 (edges) cap hit during burst | HANDLED | Drop counter incremented; `is_overloaded()` surfaces "1202-class" condition. Hamilton invariant preserved. |
| 1.10 | Scheduler P0–P2 cap hit (catastrophic burst) | SILENTLY-DEGRADES | Drops a domain or file → orphans entire subtree of children. Counter is monotonic, but **no client-visible event** says "your subtree is incomplete." |

---

## 2 — Authority internals (scheduler / log / geometry)

| # | Failure mode | Status | Evidence |
|---|---|---|---|
| 2.1 | Clock skew between threads (monotonic vs wall) | HANDLED (incidental) | Authority uses `time.monotonic()` only; no wall-clock comparison in hot path. |
| 2.2 | `_event_seq` overflow at 1e18 events | HANDLED (theoretical) | Python int is arbitrary precision; SSE wire `id:` is decimal ascii. No overflow ceiling. |
| 2.3 | `replay_since(N)` after wraparound past ring buffer (N < oldest_seq) | HANDLED | `replay_since` returns gap signal; `graph_stream` is *documented* to emit `replay_lost` and trigger snapshot fallback. **But:** the `graph_stream` SSE handler is **not wired** in `http_standalone.py` — see §5.1. So this branch is dead code in the current build. |
| 2.4 | `reset()` resets `_event_seq` (the bug the docstring warns about) | HANDLED | Code keeps seq monotonic across resets; explicit comment cites I3. |
| 2.5 | Subscriber queue full → 200 misses → evict | HANDLED | Documented; producer never blocks. |
| 2.6 | Subscriber on a Queue subclass that locks down attribute assignment | SILENTLY-DEGRADES | `_record_miss` falls back, miss count never persists, queue is **never reaped** — slow leak of dead subscribers. Documented but unfixed. |
| 2.7 | `domain` node arrives after its members (I7 race) | HANDLED | Authority computes against placeholder anchor; slot is final. Trade-off accepted. |
| 2.8 | `request_subtree` floods (viewport drag at 10 req/s) | HANDLED | `coalesce_subtree` is idempotent via linear scan (cap=100). |
| 2.9 | Geometry returns NaN for a degenerate input (e.g. 0 domains) | HANDLED | `base_radius` clamps `n_domains` to ≥1; `outward_angle` has a 5px deadzone returning `-π/2`. `compute_slot` falls back to anchor on unknown kind. |
| 2.10 | LOD `_stable_hash` collision causes uneven decimation | HANDLED | BLAKE2b 64-bit; selfcheck verifies log-log slope ≈ -1. |
| 2.11 | LOD called with `kind` not in any of the three sets | HANDLED | "fail open" — emits the unknown node, comment explicit about the intent. |

---

## 3 — Wire format

| # | Failure mode | Status | Evidence |
|---|---|---|---|
| 3.1 | Unicode in `node_id` (e.g. `cortex:utilité`) | HANDLED | Encoded as UTF-8 in `data:` payload. SSE permits UTF-8. **But:** `Content-Length` accounting at higher layer must use byte length, not char length — verified: `len(data_bytes)`. |
| 3.2 | `node_id` containing `\|` (pipe) | HANDLED | `_validate_id` raises `ValueError`. |
| 3.3 | `node_id` containing `\n` or `\r` | HANDLED | Same validation. |
| 3.4 | `node_id` longer than 32 chars | SILENTLY-DEGRADES | `_MAX_KIND` (32) is enforced **only on `kind`**, not on ids. A 10-KB node_id would be SSE-framed verbatim and shipped to the browser, blowing the wire budget per event but not crashing. |
| 3.5 | `kind` longer than 32 chars | HANDLED | `_validate_kind` raises. |
| 3.6 | Float formatted with locale-dependent decimal (`12,3` vs `12.3`) | HANDLED | f-string `:.1f` is locale-independent in Python. |
| 3.7 | Negative `seq` injected by malicious caller | SILENTLY-DEGRADES | No range check. Client `parseInt` accepts negative; ordering inverts. Authority is the only writer in current design, so de facto safe — but contract doesn't enforce. |
| 3.8 | `chunk_wrap("")` | HANDLED | Raises explicitly. |
| 3.9 | `parse_slot` on a payload with embedded `\|` in a future field | CRASHES (test-only) | `len(parts) != 5` raises. Test-only path. |

---

## 4 — Cross-build / rolling-deploy

| # | Failure mode | Status | Evidence |
|---|---|---|---|
| 4.1 | Protocol version mismatch (server adds a 6th slot field; client expects 5) | CRASHES (client) | No version negotiation in `format_slot`. Client `data.split('\|')` against a 5-vs-6 mismatch raises in JS. **No `event: protocol` handshake** in the wire. |
| 4.2 | Rolling deploy: half the fleet emits old wire, half new | CORRUPTS | Same root cause. Sticky-session SSE without an explicit version event means a client that lands on the new server then reconnects to the old server gets undefined behaviour. |
| 4.3 | `Last-Event-ID: N` from a build that no longer exists | HANDLED in design / DEAD in code | `replay_since` returns gap signal; SSE handler **is not wired** in `http_standalone.py`, so the branch never executes. |
| 4.4 | Two server processes share the same Postgres but not the same in-process `_event_log` | CORRUPTS | `_event_seq` is module-level, not coordinated. Round-robin SSE across two processes assigns the same `seq` to two different events. Out-of-process resume is broken by design. |
| 4.5 | `layout_version` clash between two simultaneous recomputes | SILENTLY-DEGRADES | `write_layout` (not audited here, but called in `run_recompute`) returns a version; if it's a timestamp ms it can collide on a fast machine. Quadtree handler reads the latest, so the loser's data is invisibly dropped. |

---

## 5 — Connection lifecycle

| # | Failure mode | Status | Evidence |
|---|---|---|---|
| 5.1 | SSE connection establishes **after** the build completes (replay-only client) | DEAD | The SSE handler that should call `replay_since(0)` and stream the historical log is **not wired into `http_standalone.py`** (grep shows no route reading from `_event_log`). The handlers `quadtree_handler` and `recompute_layout` are the only layout-related routes; they serve snapshots, not streams. So in practice the late-joining client gets a one-shot Arrow IPC blob. *That blob is internally consistent — but the entire "stream + replay" architecture documented in `_log.py` and `_wire.py` is dormant.* This is the largest map-vs-territory gap. |
| 5.2 | Browser tab paused (background tab, OS sleep) while events queue server-side | SILENTLY-DEGRADES | Subscriber queue cap 100k; 200-miss threshold evicts. Tab-resume hits a closed connection; client must reconnect, but no UI signal exists. |
| 5.3 | Out-of-order delivery across reconnect with stale `Last-Event-ID` | HANDLED in design / DEAD in code | Same as 5.1. The gap-detection branch in `replay_since` is correct but unreachable. |
| 5.4 | Client's `EventSource` auto-reconnects with stale `Last-Event-ID` after the server's ring buffer has rolled past it | DEAD | Same root cause. |
| 5.5 | Client opens 10 tabs (10 SSE subscribers) on the same authority | HANDLED | Each gets a bounded queue. Producer never blocks. |
| 5.6 | Network proxy strips `id:` lines from SSE | SILENTLY-DEGRADES | Resume is broken (no Last-Event-ID at the client), but the live stream still works. Not currently a concern because §5.1 already disables resume. |
| 5.7 | Browser tab paused for 30 min, returns; quadtree fetched `Cache-Control: max-age=60` is stale | HANDLED | `quadtree_handler` sets max-age=60; client refetches. ETag would be cleaner. |

---

## 6 — Persistence path (recompute_layout / layout_pg_store)

| # | Failure mode | Status | Evidence |
|---|---|---|---|
| 6.1 | `_graph_cache` empty when recompute is called | HANDLED | Returns `{"status":"error","reason":"no_graph_cached"}`. |
| 6.2 | igraph not installed | HANDLED | Caught as `ImportError`, surfaced as `igraph_missing`. |
| 6.3 | pyarrow not installed (quadtree path) | HANDLED | Returns 503 `viz_tile_extra_missing`. |
| 6.4 | Postgres connection drops mid-`write_layout` | CRASHES | `run_recompute` does not wrap the write in retry; exception propagates to `serve` which catches and returns 503. Caller sees `exception` reason but not transactional state. Possible partial write if `write_layout` is not atomic (not audited here). |
| 6.5 | Topology fingerprint matches but coords are stale (manual DB tamper) | CORRUPTS | `skip-if-fresh` returns the cached coords without re-reading them. Tamper is out-of-band, but the fingerprint is a coverage proof for *topology*, not *coordinates*. |
| 6.6 | `read_all_positions` returns rows with NaN in x/y | CRASHES (Arrow encode) | `pa.array(xs, type=pa.float32())` accepts NaN silently; the client then renders nodes at NaN — quadtree build collapses. The wire layer enforces finiteness on `SlotAssignment` but the persistence path does not re-validate on read. |
| 6.7 | `kind` column has a value not in NODE_KINDS (legacy row) | HANDLED | Dictionary-encoded by Arrow; client tolerates unknown kind by `_ALWAYS_VISIBLE` LOD fallback. |

---

## 7 — Map vs Territory summary

**Map (the documented + intended failure space):** ~50 distinct modes, each with a stated handling.
**Territory (what the modules actually handle today):**

- **Fully alive:** scheduler shedding, geometry NaN-safety, wire validation, LOD determinism, snapshot path (quadtree + recompute).
- **Documented but unwired (`replay_since`, `graph_stream`, ring buffer, subscriber queue):** the entire SSE streaming + Last-Event-ID resume protocol exists in `_log.py` and `_wire.py` but is **not consumed by any HTTP route in `http_standalone*.py`**. This is the central Borges finding: the *Library of Babel* of failure modes around streaming has been catalogued in code, but none of the search problems (5.1 – 5.6, 4.3) actually fire because the search is never executed.
- **Latent corruption risks:** §1.2 (concurrent builds), §1.3 (multi-producer), §4.2 (rolling deploy), §4.4 (multi-process seq), §6.4 (partial write).

## 8 — Risk-ranked findings (top 6)

| Rank | Finding | Class | Action |
|---|---|---|---|
| 1 | SSE stream + replay_since is **dead code** (§5.1, §4.3) | DEAD | Wire `graph_stream` route or delete `_log.py`/`_wire.py`. The map without territory is a 1:1 map. |
| 2 | Concurrent recomputes corrupt layout_version + reset events being drained (§1.2) | CORRUPTS | Add a build mutex or single-flight in `run_recompute`. |
| 3 | Multi-process `_event_seq` collides (§4.4) | CORRUPTS (when streaming is wired) | Move seq to Postgres sequence or constrain to single-process. |
| 4 | No protocol version handshake (§4.1, §4.2) | CRASHES on rolling deploy | Add `event: protocol` first-frame with version int. |
| 5 | `node_id` length unbounded (§3.4) | SILENTLY-DEGRADES | Add `_MAX_ID = 256` to `_validate_id`. |
| 6 | Persistence path does not re-validate finiteness (§6.6) | CRASHES at client | Add `math.isfinite` check in `read_all_positions` or `quadtree_handler`. |

## 9 — Hand-offs

- Information-theoretic event-rate analysis → **Shannon**
- Single-flight / mutex design for §1.2 + §4.4 → **Lamport / Dijkstra**
- Rolling-deploy version negotiation → **Turing** (compatibility decidability) + engineer
- Implementation of all top-6 actions → **engineer**
