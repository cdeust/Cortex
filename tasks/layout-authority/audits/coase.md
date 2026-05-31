# Coase — Transaction-Cost Audit of the Layout Authority Boundary

> Design memo: "write the layout authority as a separate Python process."
> Implementation: in-process modules (`layout_authority_{geometry,scheduler,
> log,wire,protocol,lod}.py`, all imported into `mcp_server.server`).
> Question: is the boundary in the right place?

## 1. Boundary definition

- **Inside**: counters, scheduler, slot math, event log, SSE encoder.
- **Outside**: HTTP launcher, MCP handlers, browser renderer.
- **What crosses**: `(NodeDelta | EdgeDelta) → SlotAssignment | EdgeOut`,
  ~80–112 B per event, peak ~10⁴–10⁵ evt/s sustained (Fermi §realistic peak).

## 2. Quantification — anchors

Source: cost-model.md §5 (geometry 180–300 ns/slot pure-Py),
fermi.md (encoder ~250–300 ns/event, deque/lock ~50–100 ns,
realistic peak ~3·10⁴–10⁵ evt/s), thompson.md (single-process holds to
~10⁶, breaks at 10⁷). Linux/macOS syscall and IPC numbers from Drepper
2007, Brendan Gregg flamegraph studies, kernel(7) man pages.

| Quantity | In-proc (a) | Worker thread (b) | socketpair (c) | stdin/stdout pipe (d) |
|---|---|---|---|---|
| Per-event submit | ~50 ns dict+deque | ~100 ns + 1 lock | ~3–5 µs (write+read+ctx) | ~5–10 µs (line-buf + parse) |
| Serialization cost | 0 (object ref) | 0 | ~80 B already-encoded bytes copy (memcpy) | encode+decode ~250 ns + framing |
| Context switches/event | 0 | 1 if cross-core | 2 (writer→reader→writer) | 2 + line-discipline |
| Setup latency (startup) | 0 | ~1 ms thread start | ~50 ms `fork+exec` | ~50 ms `fork+exec` + handshake |
| Crash blast radius | full server | full server | authority-only | authority-only |
| Observability | one PID, one log | one PID | 2 PIDs, 2 logs | 2 PIDs, 2 logs |
| Deploy units | 1 | 1 | 2 (parent + worker bin) | 2 + protocol versioning |
| Backpressure mechanism | bounded `queue.Queue` (free) | same | SO_SNDBUF tuning | OS pipe buffer (64 KB Linux) |

At realistic peak **10⁵ evt/s**, per-event budget is 10 µs. Options (c)
and (d) consume **30–100% of the entire budget on the boundary
crossing**, before the encoder runs.

## 3. Cost-side comparison

### (a) In-process modules — current

**Coordination costs (inside)**:
- Single GIL-shared module set; producer thread invariant (Hamilton I1/I2
  in `_log.py:25–32`) is a 7-line docstring plus a single-call discipline.
- Test surface: pytest imports modules directly. Zero IPC mocks.
- Deploy: one `pip install`, one process. Zero cross-process versioning.
- Hidden cost: GIL contention if a renderer endpoint tries CPU work in
  the same process. Mitigated because all CPU-heavy paths (numpy batch
  geometry, future) release the GIL.

**Transaction costs avoided**: zero serialization, zero IPC syscalls,
zero schema-version negotiation, zero "is the worker still alive" probe,
zero crash-recovery state transfer.

### (b) Separate worker thread

Adds one `threading.Thread` boundary; submit ~50→100 ns (extra lock).
Shared memory, shared logs, shared crash domain. Re-introduces a
two-producer race the `_log.py` I1/I2 invariant forbids unless yet
another lock is added. **Strict regression vs (a).**

### (c) Separate process via `socketpair(AF_UNIX, SOCK_SEQPACKET)`

Adds ~3–5 µs/event (Drepper 2007 §4 Unix-socket round-trip); requires
**bidirectional** codec (current `_wire.py` is one-way SSE only);
needs supervisor for SIGCHLD + counter rebuild + `seq` persistence;
two logs to correlate; per-OS SO_SNDBUF tuning (256 KB Linux / 8 KB
macOS). At 10⁵ evt/s the boundary alone consumes **~30% of the per-
event budget** before any work runs. Buys authority-crash isolation
that no rule currently demands. **Premature isolation.**

### (d) Separate process via stdin/stdout pipe

All of (c) plus byte-stream framing (length-prefix or newline-terminated;
current pipe-format is newline-free *by accident* — a `discussion`
payload with `\n` breaks it silently); macOS 16 KB default pipe buffer
holds <200 events, less than one P4 burst (cost-model §3). **Strictly
worse than (c). Refuse.**

## 4. Differentiator vs commodity

The layout authority is a **core differentiator**: the closed-form O(1)
slot math (cost-model §1–2) is the load-bearing invention; everything
else (HTTP, SSE, Postgres) is commodity. Williamson (1985) asset-
specificity argument: the authority's invariants (I1–I5 in
`layout_authority_protocol.py`) are *highly specific* to Cortex's
domain-anchored Fibonacci layout. There is no market for this
component; outsourcing it across an IPC boundary buys nothing the
in-proc form does not already provide and imposes a perpetual tax.

## 5. Transition cost

Moving from (a)→(c) is **one-way and expensive**:
- New `layout_worker_main.py` entry point + supervisor (~300 LOC).
- Bidirectional wire format (replaces one-way SSE encoder).
- Crash-recovery state machine (rebuild counters from log on restart).
- Test harness: subprocess fixtures, fake socketpair, port allocation.
- Empirical cost from the untracked `mcp_server/server/layout_worker_main.py`
  in this branch: someone started this and stopped — evidence that the
  transition cost is non-trivial and was not justified by measured benefit.

Payback period at 10⁵ evt/s peak: **never**, because the IPC tax is
paid on every event forever and the only purchased property
(authority-crash isolation) does not currently rank in the top-10
production incidents (no incident log shows authority crashes).

## 6. Non-economic constraints check

| Constraint | Forces process boundary? | Why |
|---|---|---|
| Security / sandboxing | No | All modules trust the same input set. |
| Compliance | No | No regulated data crosses this boundary. |
| Fault isolation | Marginal | Authority is pure-Py + closed-form; crash modes are bugs (caught by tests), not hardware faults. Hand off to Hamilton. |
| GIL contention | Not yet | Geometry releases GIL in numpy path (§5 cost-model). If a *separate CPU-bound* renderer-side workload appears, revisit. |
| Memory pressure | No | Authority working set ≤ 56 MB (`_log.py`) — fits one process trivially. |

None override the cost analysis at current scale.

## 7. Scaling re-evaluation (cross-ref Thompson)

Thompson's table shows the boundary should move at **N ≥ 10⁷**, not
because of IPC economics but because the *form itself* must change
(per-domain sharding, then tile pyramid). At that point the question
is no longer "thread vs socketpair" but "11 sharded authorities vs
one tile-server". Moving to (c) *now* prepays a cost for the wrong
problem.

## 8. Recommendation

**Keep (a) in-process modules.** The shipped agents made the right
call against the design memo. Justification:

1. At realistic peak (10⁴–10⁵ evt/s) options (c)/(d) consume 30–100%
   of the per-event budget on boundary crossing alone.
2. The single-producer invariant (`_log.py` I1/I2) is *cheaper* to
   enforce in-proc than to re-implement across an IPC channel.
3. No non-economic constraint forces a process boundary at this scale.
4. The Coase test: coordination cost inside (one producer-thread
   discipline, ~10 lines of docstring) ≪ transaction cost outside
   (bidirectional wire codec + supervisor + crash recovery + per-OS
   buffer tuning + dual log correlation).
5. Williamson asset-specificity is high; the component is a
   differentiator; in-house = in-proc is the cost-minimizing form.

**The boundary moves only when**: (i) Thompson's 10⁶→10⁷ shard transition
arrives, at which point the new boundary is **per-domain authority
shards over shared memory**, not parent/child pipes; or (ii) a measured
authority-crash incident causes user-visible HTTP downtime — at which
point fault isolation becomes a real, not hypothetical, budget item.

## 9. Hand-offs

- **Hamilton**: design the SHM/mmap shard boundary for the 10⁷ transition.
- **Thompson**: confirm form-change point (10⁶ → 10⁷) with measured
  end-to-end at 10⁶.
- **Engineer**: delete the untracked `layout_worker_main.py` stub or
  document it as "explored, rejected — see coase.md".
- **Curie**: instrument actual authority-crash frequency before any
  future fault-isolation argument is admitted.

## 10. Compliance check (against `~/.claude/rules/coding-standards.md`)

| Rule | Status | Note |
|---|---|---|
| §1 SOLID | pass | Decision preserves SRP per module; rejecting (b) avoids LSP breakage of the single-producer invariant. |
| §2 Layer dependency | pass | (a) keeps server-layer composition intact; (c)/(d) would require new infra/transport modules with no current caller. |
| §7 Local reasoning | pass | (a) keeps behavior readable from the surrounding text; (c)/(d) defeat local reasoning across the process boundary. |
| §8 Sources | pass | All quantitative claims sourced to cost-model.md, fermi.md, thompson.md, Drepper 2007, kernel man pages. |
