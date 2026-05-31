# Hart Audit — Open Texture in the Layout-Authority Protocol

> Method: every rule has a **core** of settled meaning where application is
> mechanical, and a **penumbra** where the rule's text underdetermines the
> outcome. In the penumbra, judgment is needed — and that judgment is binding
> precedent for similar future cases. This audit catalogues the penumbral
> zones in `mcp_server/server/layout_authority_protocol.py` (I1–I7) and the
> hidden invariants surfaced by Noether (H1–H5), and recommends, per zone,
> whether to **close** the texture or **leave it open** as deliberate
> flexibility. Sources: Hart 1961 Ch. VII; Levi 1949 Ch. 1.

---

## 1. Open textures, ranked by load-bearing risk

### OT‑1. I3+I4 interaction: does the symbol get reseated when its file does? — **HIGH. CLOSE.**
- **Core.** I3: symbol slot computed from parent file. I4: file slot at fallback anchor is FINAL.
- **Penumbra.** File F arrives without tool_hub → S_F at domain anchor (Case 4) → symbol s with parent=F arrives → s computed from S_F → tool_hub T arrives later. I4 forbids reseating F. Protocol is **silent on s**: was s computed against a transient parent and now stale? Finality is inherited only by implication.
- **Close — add I3a.** *"A symbol's slot is final from the moment its parent file's slot is final. Since file slots are final by I4, symbol slots are final on first emission."* Same justification as I4: replay determinism (H3), no retroactive jitter.
- **Ratio.** Slot finality propagates down the parent chain. Any node whose slot is computed from another's inherits parent finality at emission time. (Generalises to nested symbols, member_of chains.)

### OT‑2. I7 placeholder anchor: WHAT is the placeholder? — **HIGH. CLOSE.**
- **Core.** I7: members of a not-yet-arrived domain use a "placeholder anchor"; FINAL.
- **Penumbra.** Two readings: (a) placeholder = `domain_anchor(index_of(D), N_CAP, …)` from a deterministic index, identical to the eventual real anchor; (b) placeholder = generic default like `(cx, cy)`. Reading (b) breaks H3 (real domain emits at its slot far from the cluster).
- **Close — adopt (a).** *"Placeholder anchor for not-yet-emitted domain D = `domain_anchor(stable_index(D), N_CAP, cx, cy, base_r)`, computed from D's `domain_id` via a deterministic index function. Placeholder == final."* Only reading consistent with H2 + H3.
- **Ratio.** Any "fallback"/"placeholder" in this protocol MUST equal the eventual real value modulo timing. (Generalises OT‑1.)

### OT‑3. I4 "domain hub" fallback for files: which (x, y)? — **MEDIUM. CLOSE.**
- **Core.** "Falls back to placing the file at the domain hub if no tool_hub is yet known."
- **Penumbra.** "Domain hub" ambiguous: (a) the domain anchor itself (collision — N files stack on one point); (b) `compute_slot(domain_anchor, kind='file', idx=arrival_idx)` — the kind-bucket for files.
- **Close — adopt (b).** *"When a file's primary tool_hub is unknown at add_node time, it is placed via `compute_slot(domain_anchor, kind='file', idx=file_arrival_idx)` — the kind='file' bucket of the domain, not the anchor itself."*
- **Ratio.** "Falls back to X" never means "stacks on point X." Fallback = closest well-defined kind-bucket reachable without the missing parent.

### OT‑4. request_subtree scope: what counts as "the subtree"? — **MEDIUM. CLOSE.**
- **Core.** request_subtree(domain_id) re-emits one subtree.
- **Penumbra.** Includes (i) only direct domain members, (ii) + files, (iii) + symbols, (iv) transitive parent_id closure rooted at domain? Also: do buffered (not-yet-emitted) symbols/edges flush, or only known nodes re-emit?
- **Close — (iv) + no flush.** *"Re-emits SlotAssignment for every node whose `domain_id == d` AND every node whose ancestor chain via parent_id terminates at a node with `domain_id == d`. Buffered symbols and pending-edges are NOT flushed; buffering invariants (I3, I5) are unchanged."* Idempotent and bounded.
- **Ratio.** request_subtree is re-emission of *known* state, not flush of *pending* state.

### OT‑5. I5 "oldest dropped" — by which clock? — **MEDIUM. CLOSE.**
- **Core.** Pending-edges full ⇒ "oldest" dropped, counter ++.
- **Penumbra.** "Oldest" by (a) wall-clock receive, (b) seq order at buffer insert, (c) age relative to missing endpoint?
- **Close — (b).** *"'Oldest' = earliest insertion into pending-edges, FIFO by arrival sequence number. Wall-clock not used (preserves H3)."*
- **Ratio.** Tie-breakers in this protocol use deterministic counters, never wall-clock. (Generalises to any future "oldest"/"first" rule.)

### OT‑6. I2 "per authority instance" scope — **MEDIUM. CLOSE.**
- **Core.** seq strictly increasing per authority instance.
- **Penumbra.** (a) Restart — seq reset or persisted? (b) Per-subscriber queue racing — must per-queue order match seq order? (c) request_subtree re-emit — fresh seq or restate old?
- **Close.** *"(a) seq resets to 1 on restart; (instance_id, seq) is the global identity. (b) Per-subscriber delivery order MUST match seq order — declare alongside H1 as I8. (c) request_subtree re-emissions get NEW higher seq; clients resolve by seq (consistent with I2 'LATER supersedes')."*
- **Ratio.** seq is the single source of truth for ordering; every restatement gets a fresh seq.

### OT‑7. NodeDelta.parent_id "if known" for files — **MEDIUM. CLOSE.**
- **Core.** For 'file', parent_id = primary tool_hub's id "if known."
- **Penumbra.** What if file legitimately has NO primary tool_hub (e.g. doc never tool-touched)? Permanent None, or reseat on first tool_used_file edge? I4 says no reseat — but rule was written assuming the hub eventually arrives.
- **Close.** *"A file with parent_id=None whose tool_hub never arrives remains permanently at the kind='file' bucket of its domain anchor. Later tool_used_file edges do NOT trigger reseat (I4)."*
- **Ratio.** Optional fields that never materialise yield permanent fallbacks, never lazy reseat.

### OT‑8. Duplicate node_id (was H5) — **HIGH. CLOSE.**
- **Core.** Protocol silent. Noether H5: "node_id is a primary key" — undeclared.
- **Penumbra.** Second `add_node(same_id)` (a) silently ignored, (b) raises, (c) treated as update (e.g. late tool_name on tool_hub)?
- **Close — (a) + counter.** *"Second add_node with existing node_id is silently ignored; duplicate_counter ++. No SA re-emitted. The build worker MUST NOT use add_node as an update mechanism; use request_subtree for forced re-emission."* Promote to I9.
- **Ratio.** Idempotence at the input boundary is invariant; updates require an explicit verb.

### OT‑9. EdgeDelta endpoints arriving in opposite order — **LEAVE OPEN.**
- **Penumbra.** When second endpoint arrives, is buffered edge flushed (a) immediately interleaved with SA stream, (b) after next SA, (c) batched at end of current add_node?
- **Leave open + document.** Edges carry no slot data; (a)/(b)/(c) are observationally equivalent. *"Pending-edge flush order relative to SlotAssignment is implementation-defined; clients MUST NOT rely on a specific interleaving."*
- **Ratio.** Leave open what the contract does not need to fix; documenting the freedom IS the closure.

### OT‑10. Authority restart / persistence — **LEAVE OPEN (out of scope).**
- **Penumbra.** No rule covers crash recovery, log replay on restart, instance migration.
- **Leave open + hand-off.** Out of scope for the streaming protocol; defer to a separate persistence ADR. Note in protocol docstring: *"Restart semantics are defined by the host process, not this protocol."*

---

## 2. Closure summary

| OT | Subject | Decision |
|---|---|---|
| OT‑1 | Symbol-slot finality vs file fallback | **CLOSE** — add I3a |
| OT‑2 | I7 placeholder formula | **CLOSE** — deterministic anchor |
| OT‑3 | I4 "domain hub" precise meaning | **CLOSE** — kind='file' bucket |
| OT‑4 | request_subtree scope | **CLOSE** — transitive, no flush |
| OT‑5 | "Oldest" pending edge | **CLOSE** — FIFO by arrival seq |
| OT‑6 | seq across restart / re-emit | **CLOSE** — instance_id + new seq |
| OT‑7 | File with no tool_hub ever | **CLOSE** — permanent fallback |
| OT‑8 | Duplicate node_id | **CLOSE** — ignore + counter (I9) |
| OT‑9 | Pending-edge flush order | **LEAVE OPEN** — document freedom |
| OT‑10 | Restart / persistence | **LEAVE OPEN** — separate ADR |

---

## 3. Governing principles (ratio decidendi for future open textures)

1. **Finality propagates down parent chains** (OT‑1).
2. **Fallbacks must equal the eventual real value modulo timing** — divergence breaks H3 (OT‑2, OT‑5).
3. **"Falls back to X" is never "stacks on point X"** — use closest kind-bucket (OT‑3).
4. **Re-emission verbs restate known state; they do not flush pending state** (OT‑4).
5. **Tie-breakers use deterministic counters, never wall-clock** (OT‑5, OT‑6).
6. **Optional fields that never materialise yield permanent fallbacks** — never lazy reseat (OT‑7, matches I4).
7. **Idempotence at the input boundary is invariant; updates require an explicit verb** (OT‑8).
8. **Document deliberate freedoms as freedoms** — recorded openness is itself precedent (OT‑9, OT‑10).

---

## 4. Hand-offs

- **Engineer** — translate OT‑1…OT‑8 into protocol docstring amendments + assertions in `layout_authority.py`.
- **Lamport** — formalise OT‑6 (seq across restart) and OT‑5 (FIFO by arrival seq) as TLA+ invariants alongside H1.
- **Noether** — H5 closed by OT‑8 ⇒ promote to I9 in `_protocol.py`; H1 still pending as I8.
- **Alkhwarizmi** — extend test 5 (duplicate node_id) and add golden-vector tests for OT‑1, OT‑2, OT‑3 fallback positions.
