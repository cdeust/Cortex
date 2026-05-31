# Lavoisier audit — layout authority mass-balance

Conserved quantity: **events**. Every input verb (`add_node N`,
`add_edge E`, `request_subtree K`) MUST resolve to either an outbound
SSE frame or one increment of a named counter. No silent loss.

## Conservation law

```
N add_node          = N_emitted_slots  + scheduler.dropped[P0..P4]
                                        + scheduler.lengths[P0..P4]   (in flight)
                                        + parent_pending (I3 buffer)  ← UNBUILT, LEAK
                                        + format_failures             ← UNBUILT, LEAK
E add_edge          = E_emitted_edges  + scheduler.dropped[P5]
                                        + scheduler.lengths[P5]
                                        + edge_pending (I5 buffer, "counter
                                          incremented") ← UNBUILT, LEAK
K request_subtree   = K' re-emissions  + scheduler.dropped[P6]
                                        + coalesced duplicates ← UNCOUNTED, LEAK
(once)              = 1 done frame
log overflow        = _event_log_drops                                (covered)
subscriber overflow = reaped subscriber                               (count NOT exposed)
```

`layout_authority.py` does not exist yet. The audit covers `protocol`,
`scheduler`, `log`, `wire`. Every leak below is a contract the next
engineer must seal.

## `layout_authority_protocol.py` — contract-only

The contract IS the ledger spec. Two mandated buffers are the
load-bearing residuals: I3 (symbol waits on parent file) and I5
(pending-edges, 100k cap, "oldest dropped, counter incremented").
Neither buffer nor counter exists in any shipped module. Until built,
the books cannot close on real load.

I7 (domain may arrive after members) is not a count loss but a *value*
loss — slots placed against placeholder anchor are FINAL. Out of scope
for mass-balance; flagged for Curie (carrier isolation) or Popper
(falsifiability of the placement).

## `layout_authority_scheduler.py` — closes for what it owns

```
submit():    True  → stats.queued[p] += 1   (eventually pop()'d → consumer's job)
             False → stats.dropped[p] += 1  (named residual)
             unknown p → ValueError         (loud, no silent loss)
coalesce():  new       → queued[6] += 1
             duplicate → returns False, NO counter ← LEAK
             cap       → dropped[6] += 1
pop():       (p,item) → consumer owns balance from here on
             timeout  → None, no counter needed
priority_for_node(): unknown kind → P3 silently ← LEAK
```

Producer-never-blocks invariant holds (no `put()`, only `append` after
lock). **But once `pop()` returns, an unwritten worker must call
either `emit()` or a counter; no module currently does this.**

Residuals here:
- Coalesced duplicates `K - K'` invisible. Cost to seal: `stats.coalesced[6]`.
- Unknown kinds silently routed to P3. Either count as `unknown_kind_to_p3`
  or raise. Currently neither.

## `layout_authority_log.py` — cleanest, two real holes

```
emit(): seq += 1
        log full → _event_log_drops += 1, deque evicts oldest
        fan_out: put_nowait OK → delivered
                 put_nowait raises → _record_miss; >200 → reaped
reset(): clears log + drops; KEEPS _event_seq monotonic (correct per I3)
```

Hole 1 — **reaped subscribers not exposed.** `_reap()` removes from
list, never bumps a published counter. `stats()` reports current
`subscribers` (live), not cumulative reaped. A reaped (slow) client is
indistinguishable from a clean `unsubscribe()`. Cost to seal: one
global `_subscribers_reaped` in `stats()`. Operationally meaningful —
this is the SLA evidence for slow-client eviction.

Hole 2 — **`_record_miss` swallows attribute-set failures.** Lines
67–71: `except Exception: pass`. A Queue subclass that locks attribute
writes never trips the dead-queue threshold; misses reset to 1 every
call → that subscriber holds 11 MB forever. Comment calls it
"acceptable degradation"; it is an accounting hole. Fix: keep misses
in a module-scope `WeakKeyDictionary[Queue, int]`. (Move 4 alternative:
narrow the subscriber type so the failure mode cannot exist.)

Hole 3 — **`_record_miss` increments on ANY exception**, not only
`Full`. `RuntimeError` from a broken queue, `MemoryError` from OOM,
all conflated as "slow subscriber". Narrow the `except` to
`queue.Full`.

## `layout_authority_wire.py` — pure encoder, sealed

| Input | Output | Failure path |
|---|---|---|
| `SlotAssignment` | `format_slot` bytes | `_validate_id`/`_validate_kind`/`_validate_finite` → `ValueError` (loud) |
| `EdgeDelta` | `format_edge` bytes | same |
| `(total_slots, total_edges)` | `format_done` bytes | raises on negative |

Every rejection is a raise, never a silent drop. Conservation upheld
*locally*. **But:** if the unwritten worker pops a bad delta and
`format_slot` raises, the event is gone — popped, never emitted, no
counter. The implementation MUST wrap every `format_*` call with
try/except + `format_failures` counter.

## Sealed-system check — NOT sealed

Two boundary leaks:

1. **Inputs to `add_node`/`add_edge` flow through pending-buffers that
   don't exist in code yet.** Decisions to buffer-or-place happen
   *before* `submit()`, so existing `Stats` cannot cover them. Add
   sibling `BufferStats` to `layout_authority.py`:
   `parent_pending_high_water`, `parent_pending_dropped`,
   `edge_pending_buffered`, `edge_pending_dropped`.
2. **Outputs to subscribers asymmetrically counted.** Log counts
   emits; subscribers count nothing. A subscriber that `unsubscribe()`s
   with queued events loses them silently. Add `events_delivered` per
   subscriber, `events_undelivered_at_unsubscribe` global.

## Conservation filter on claims

| Claim | Conserves? | Verdict |
|---|---|---|
| "Stats covers all drops" | NO — pending buffers + format errors uncounted | reject |
| "Single seq is enough for client correctness" | YES — gap → snapshot fallback | accept |
| "Coalesced subtree requests don't need counting" | NO — gap invisible | accept only if explicitly designed; else add counter |
| "`except Exception` in `_record_miss` is fine" | NO — conflates Full / Broken / OOM | reject; narrow to `queue.Full` |

## Terminology (Move 4)

| Current | Problem | Proposed |
|---|---|---|
| `Stats.queued` | Reads as "currently queued"; is cumulative submits | `submitted_total` |
| `_event_log_drops` | Ambiguous mechanism | `log_overflow_evictions` |
| `priority_for_node` returns P3 for unknown | Silent fallback hidden in name | `priority_for_node_or_default` + counter |

## Hand-offs

- **Pending-buffer isolation (I3, I5)** → Curie. Largest unbalanced
  residual; cap, age-eviction, counters once `layout_authority.py` exists.
- **Reaped + format-failure magnitudes at 1e9 load** → Fermi.
- **Quantity definition** → Shannon. If `request_subtree` re-emits,
  input-nodes ≠ output-slots; formalize "conserved" before impl ships.

## Action items (priority order)

1. (BLOCKING) `layout_authority.py` must add `BufferStats` covering
   symbol-parent-pending and edge-pending; expose via
   `/api/layout/stats`.
2. (BLOCKING) Wrap every `format_*` call in worker loop with
   try/except + `format_failures` counter.
3. Expose `subscribers_reaped_total` in `_log.stats()`.
4. Narrow `_record_miss` exception to `queue.Full`; replace
   `q._cortex_misses` attr write with module-scope
   `WeakKeyDictionary[Queue, int]`.
5. Add `stats.coalesced[6]` — count duplicate `request_subtree`.
6. Rename `Stats.queued` → `Stats.submitted_total`.
7. Add `unknown_kind_routed_to_p3` counter (or raise) in
   `priority_for_node`.

## Files touched

None. Audit-only.
