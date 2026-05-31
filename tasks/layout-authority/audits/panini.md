# Panini Audit — Generative Grammar of the Layout Authority Event Stream

Scope: the SSE wire stream produced by the consolidated authority
(`_protocol` + `_geometry` + `_scheduler` + `_log` + `_wire`) and
consumed by `ui/unified/js/polling.js` / `workflow_graph_bridge.js`.
Goal: a grammar that produces **all** valid streams and **no** invalid
ones, plus identification of constraints currently enforced only by
convention.

Stakes: **High** — every UI invariant downstream rests on the stream
being well-formed.

---

## 1. Terminal alphabet (events on the wire)

From `layout_authority_wire.py`:

```
SLOT(seq, id, x, y, kind, domain_id)        event: slot
EDGE(seq, src, tgt, kind)                    event: edge
DONE(seq, total_slots, total_edges)          event: done
PING                                         : ping        (SSE comment)
```

Each event also carries `id: <seq>` for `Last-Event-ID` resume.

---

## 2. Generative grammar (BNF + side-conditions)

The naive `STREAM := EVENT* DONE` is correct as a sequence shape but
under-specifies dependencies. Slots and edges genuinely interleave, so
linearisation alone is not enough — we need an **attribute grammar**
whose side-conditions reference the prefix already emitted.

```
STREAM      := SESSION (RESET SESSION)*
SESSION     := PING* EVENT_RUN PING* DONE
EVENT_RUN   := EVENT*
EVENT       := SLOT | EDGE | PING
SLOT        := slot(seq, id, x, y, kind, domain_id)
EDGE        := edge(seq, src, tgt, ekind)
DONE        := done(seq, total_slots, total_edges)
RESET       := <implicit on _log.reset(); seq does NOT rewind>
```

### Side-conditions (the actual generative power)

Let `Σₙ` denote the multiset of slots emitted strictly before position
`n`, and `slot[id]` the unique slot in `Σₙ` with that id (if any).

* **G1 Sequence monotonicity.** For any two events `eᵢ, eⱼ` with `i<j`:
  `eⱼ.seq > eᵢ.seq`. Strictly increasing across the **entire** authority
  lifetime, including across `RESET` (per `_log.reset` docstring).
* **G2 Kind closure.**
  `slot.kind ∈ NODE_KINDS`, `edge.ekind ∈ EDGE_KINDS`
  (`_protocol.NODE_KINDS`, `EDGE_KINDS`).
* **G3 Slot id uniqueness.** Within a SESSION, `slot.id` is unique
  unless preceded by a `request_subtree` invalidation containing that id;
  later `(seq)` supersedes earlier (`I2`).
* **G4 Domain anchor.** For every `slot` with `kind == 'domain'`:
  `slot.id == slot.domain_id`. (`NodeDelta` precondition.)
* **G5 Domain referential integrity.** For every `slot s`:
  `∃ s' ∈ Σ : s'.kind == 'domain' ∧ s'.id == s.domain_id`. The domain
  anchor MAY arrive **after** its members (`I7`); the constraint is on
  the SESSION as a whole, not on the prefix at every position.
* **G6 Edge endpoint precedence.** For every `edge(src,tgt,_)`:
  `slot[src] ∈ Σ` AND `slot[tgt] ∈ Σ`. The authority buffers edges
  whose endpoints have not landed (`I5`); buffering is internal — on
  the wire G6 holds prefix-locally.
* **G7 Symbol parent precedence.** For every `slot s` with `kind ==
  'symbol'`: `∃ p ∈ Σ : p.id == NodeDelta(s).parent_id ∧ p.kind ==
  'file'`. Buffered until parent file's slot is emitted (`I3`).
* **G8 File parent best-effort.** For every `slot` with `kind ==
  'file'`: parent `tool_hub` MAY be missing; placement falls back to
  domain hub (`I4`). NOT a hard constraint.
* **G9 Coordinate finiteness.** `math.isfinite(slot.x) ∧
  math.isfinite(slot.y)` (`I1`, enforced in `_wire._validate_finite`).
* **G10 Delimiter purity.** No id, kind, or domain_id contains `|`,
  `\n`, `\r` (`_wire._validate_id`, `_validate_kind`).
* **G11 DONE termination.** `DONE` appears at most once per SESSION;
  `DONE.total_slots == |{e ∈ SESSION : e is SLOT}|` and likewise for
  edges. After `DONE`, only `PING` or `RESET` may follow.
* **G12 Tool-hub naming.** For every `slot` with `kind == 'tool_hub'`:
  the originating `NodeDelta.tool_name` is non-empty (`NodeDelta` Pre).
  The wire does not currently carry `tool_name`, so this is a
  build-side, not stream-side, constraint — see §4 D-G12.

A stream is **valid** iff it is derivable under the above. It is
**invalid** iff any side-condition fails.

---

## 3. Conflict-resolution meta-rules (paribhāṣā)

The grammar's rules can compete; explicit precedence:

* **M1 Domain-late vs slot-emit.** When a non-domain slot is ready but
  its domain anchor has not arrived: emit anyway against placeholder
  anchor; slot is FINAL (`I7`). G5 holds session-globally, not
  prefix-locally. (Precedence: `I7` > strict G5.)
* **M2 File-late vs symbol-emit.** Symbols WAIT for parent file;
  buffered, not faulted. (Precedence: `I3` > liveness for symbols.)
  Asymmetric with M1 because symbol coordinates are computed *from*
  the file slot, not from the domain anchor.
* **M3 Buffer overflow vs liveness.** Pending-edges buffer at cap →
  drop oldest with counter (`I5`). The grammar tolerates a pruned
  suffix; it MUST NOT tolerate ill-formed events.
* **M4 Reset vs resume.** `Last-Event-ID: N` after `RESET` with
  `oldest_seq > N+1` ⇒ `replay_lost` sentinel (`_log.replay_since`),
  client falls back to snapshot. Seq counter NEVER rewinds across
  reset, by I3-prose (the prose, not the original code body, is
  authoritative — see `_log.reset` docstring).

---

## 4. Constraints currently NOT enforced structurally

The current 5-module split enforces some constraints by **assertion in
docstrings + reviewer discipline**, not by structure. Each row names
the gap, where it would be caught, and what would make it structural.

| ID | Constraint | Where (in)visible | What is enforced today | Structural fix |
|----|-----------|-------------------|------------------------|----------------|
| **D-G1** | Single-producer monotonicity of `seq` | `_log.emit` | Prose only ("MUST be called from a single producer thread"). Two threads can interleave `seq` assignment + fan-out and break per-subscriber order. | Assert `threading.get_ident()` matches a captured producer-thread-id at `emit` entry. (Already flagged by Dijkstra D1.) |
| **D-G3** | Slot id uniqueness within a SESSION | nowhere | `_protocol` says "unique"; `_log` does not check; `_wire` does not check. A double-`add_node` for the same id silently emits two slots with different seq → client sees "node moved." | A small `set[str]` of emitted slot ids in the authority's main store; reject (or coalesce) duplicates at `add_node` time. |
| **D-G6** | Edge-endpoint precedence on the WIRE | `_protocol.EdgeDelta` Pre, `I5` | The protocol says "buffer until both endpoints arrive"; the buffer is internal to the (yet-unwritten) `layout_authority.py`. The 5 modules as shipped have **no buffer** — `_scheduler` does not know about edge dependencies, and `_log` will happily emit an `edge` whose endpoints have never been emitted as slots. | Edge admission gate in the authority main loop: pop edge → check both endpoints in slot-id set → emit OR push to pending-edges deque keyed by missing endpoint. This is exactly the missing piece. |
| **D-G7** | Symbol→file parent precedence | `_protocol` `I3` prose | Same as D-G6: today, nothing structurally forces the file's slot to be emitted before any of its symbols' slots. `_scheduler` orders by *priority* (file=P2 < symbol=P4) but priority does not encode dependency: a P4 symbol whose file is queued at P2 can still pop after its file IF the worker drains P0..P4 in order — only because of a coincidental priority gradient, not a real dependency check. | Per-symbol "blocked-on" set in the authority store; release when parent file slot is emitted. Same machinery as D-G6. |
| **D-G5** | Every `domain_id` resolves to a `kind=='domain'` slot in the SESSION | `_protocol` `I7` | Not checked at `done` time. A SESSION can legally end with `DONE` while some `domain_id` referenced by member slots was never accompanied by its anchor. | At `DONE` emission, validate every observed `domain_id` is in the set of emitted-domain ids; if not, emit a deferred placeholder anchor first. |
| **D-G11** | `DONE.total_slots / total_edges` consistency | `_wire.format_done` | Only checks non-negativity. The authority computes the totals; nothing cross-checks against the actual fan-out count. | Counter incremented by `_log.emit` for each kind; `format_done` consumes those counters rather than caller-supplied numbers. |
| **D-G10** | Delimiter purity | `_wire._validate_id` | Caught at the WIRE boundary, not at protocol boundary — late. By the time `_wire` raises, the event has already been `submit`-accounted in `_scheduler`. | Move `_validate_id` / `_validate_kind` into `add_node` / `add_edge` entry. (Dijkstra D-pre also flags this.) |
| **D-G12** | `tool_name` non-empty for `tool_hub` | `_protocol.NodeDelta` Pre | Documented; not asserted at construction (`NodeDelta` is a frozen dataclass without `__post_init__`). | Add `__post_init__` to `NodeDelta` raising `ValueError` for the per-kind preconditions enumerated in its docstring. |

### The single most load-bearing structural gap

**D-G6 / D-G7 — endpoint and parent precedence are not enforced
structurally.** They are stated in `_protocol`'s `I3`/`I5` prose and
expected to be honoured by a **reference implementation that does not
yet exist** (`layout_authority_protocol.authority_from_geometry`
forward-imports `layout_authority.build_authority`, which is unwritten
in the 5 modules under audit). The scheduler orders by priority and the
log fans out FIFO; nothing in the 5 shipped modules enforces "EDGE only
after both SLOTs" or "SYMBOL slot only after FILE slot." On any
out-of-order arrival from the build worker the wire WILL emit an
ill-formed stream (G6 / G7 violated), and the client will draw edges to
non-existent nodes or symbols at the domain hub instead of inside their
file petal.

---

## 5. Economy (lāghava) check

* 12 generative rules (G1–G12) cover the full event stream — comparable
  to the rule density of the existing audits' invariants.
* 4 conflict-resolution meta-rules (M1–M4) replace what would otherwise
  be ~7 ad-hoc "what if X arrives before Y" branches.
* 8 structural gaps (D-G*) all collapse to **one missing module**:
  the authority main loop with two small data structures (slot-id set,
  pending-by-endpoint map). This is the Pāṇinian compression — most
  apparent gaps share a single unwritten origin.

---

## 6. Hand-offs

* **Knuth** — implement the slot-id set + pending-by-endpoint map with
  the exact O(1) amortized cost the closed-form geometry promises.
* **Dijkstra** — pre/post conditions in §1 align with D0–D2 of his
  audit; integration must satisfy both.
* **Popper** — the negative tests are: (a) emit edge before either
  endpoint, (b) emit symbol before its file, (c) emit two slots with
  the same id, (d) emit member slot whose domain_id never appears.
  Each must fail **structurally** post-fix, not by reviewer catch.
