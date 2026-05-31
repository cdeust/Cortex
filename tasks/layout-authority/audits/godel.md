# Layout Authority — Gödel Self-Reference Audit

**Method:** Gödel's incompleteness pattern. The layout authority is a system that emits sentences ("node N is at (x,y) at seq S"). Every totalizing claim it makes — "seq is GLOBAL", "slot is FINAL", "x,y is finite" — is a meta-statement *about the system* expressed *within the system's own vocabulary*. Where the vocabulary is rich enough to encode the authority's own state (counters, ids, totals), Gödel sentences become constructible: true statements about the system that the system cannot prove from within its own emission rules.

This audit surfaces those sentences and the structural contradictions they expose.

---

## 1. Self-reference power assessment

Does the authority have the expressive power for self-reference? Yes:

- **Counters are addressable.** `_event_seq`, `_slots_emitted`, `_edges_emitted`, `_edges_dropped`, `pending_*` are all readable via `stats()` and via `_log._event_seq` peeks inside `_emit_slot` / `done`.
- **Ids are unconstrained strings.** `_validate_id` rejects `|`, `\n`, `\r` only. An id like `"seq:42"` or `"slots_emitted:0"` is legal. Therefore a NodeDelta's `node_id` can name an authority counter.
- **The done event is itself an event.** It consumes a seq, increments no slot counter, but is logged in `_event_log` and reported by `_log.stats()` as `newest_seq`. The system's terminator is a sentence in its own log.

Conclusion: incompleteness applies. The authority is "powerful enough to describe itself" in the Gödel sense, because its emission language can refer to its own counters by string id and its own seq numbers by peek.

---

## 2. Constructed Gödel sentences

| # | Sentence (concrete) | Why true | Why unprovable from within |
|---|---|---|---|
| **G1** | "The next slot's `node_id` equals `f'seq:{_log._event_seq + 1}'`." | Build worker is free to construct this id (no validation rule forbids it). | The seq the slot will receive is computed at emit time by `_log.emit`, *after* the payload is formatted. The peek-before-emit at `layout_authority.py:349` formats the payload using the predicted seq; if a multi-producer race ever interleaved an emit between peek and write, the slot's *content* would name a seq that is no longer its own. The assertion `actual_seq == seq` *detects* this but cannot *prevent* it — and the assertion fires *after* the SSE byte stream has already been formatted. The sentence "this slot's id equals its own seq" is true in single-producer mode and undecidable in concurrent mode. |
| **G2** | "The `done` event's `total_slots` counts every slot including the one whose seq is the `done` event's own seq." | False, but the system claims it via the `done` payload semantics. `total_slots = self._slots_emitted` is sampled *before* `_log.emit("done", ...)`. The done frame's seq is `_event_seq + 1` at peek time, then `+1` at emit. So `done.seq > total_slots` always. | The `done` payload offers no field to declare its own seq, and `total_slots` is documented as "totals". A client reading `total_slots == newest_seq - 1` would be wrong by 1 for every build that has any edges, and wrong by N for builds with N edges. The system cannot prove the relation `newest_seq = total_slots + total_edges + 1` from within its own payload contract, because the wire layer never emits that arithmetic. |
| **G3** | "After `reset()`, the new log's `oldest_seq` is greater than every `Last-Event-ID` a client might present." | True by construction (counter is global, never rewinds). | But `replay_since(N)` returns `(events_to_replay, oldest_available_seq)` and the SSE handler uses `oldest_available_seq > since + 1` to detect a gap. Immediately after `reset()` the deque is empty, so `_event_log[0]` is undefined and the function returns `[], 0`. A client that reconnects in the dead window between `reset()` and the first new `emit()` is told `oldest=0`, which fails the gap test (`0 > since + 1` is false for any positive `since`). The sentence "no events are lost across reset" is true; the sentence "the log can prove no events are lost across reset" is false during the reset/first-emit window. |
| **G4** | "Every `SlotAssignment` for a given `node_id` is FINAL (I4, I7)." | Asserted by invariants. | But `request_subtree(domain_id)` re-emits *every* slot in that domain *with a fresh seq* (`_emit_slot` reads `_log._event_seq + 1` again). I2 says clients "MUST update by seq" — i.e. the later seq supersedes. So a slot is simultaneously FINAL (I4/I7) and supersedable (I2). The system contains a direct contradiction whose witness is constructible: call `request_subtree(d)` twice, observe two `SlotAssignment` tuples for the same node_id with different `seq` and identical `(x,y)`. The second is "newer" by I2 but identical by I4. The system has no rule by which a client decides whether to honor the second event's seq update or treat it as a no-op. |
| **G5** | "`stats()` returns counters that describe the moment of the call, not including the call itself." | True by construction — `stats()` is read-only, emits no event, increments no counter. | But the seq counter `_event_seq` is reported via `_log.stats()['newest_seq']`, and the *next* event after a `stats()` call will be `newest_seq + 1`. A client reading stats then issuing `add_node` cannot prove that no other producer emitted between its read and write; the sentence "the next slot will have seq = stats().newest_seq + 1" is true under the single-producer precondition and unprovable from outside that precondition. The single-producer rule lives in a *prose docstring*, not in the type system. |
| **G6** | "There exists a `NodeDelta` whose `node_id` is the string representation of an authority counter, and whose emission *changes* that counter." | Constructible: `NodeDelta(node_id="slots_emitted:0", kind="domain", domain_id="slots_emitted:0")`. After emission, `self._slots_emitted == 1` while the slot whose id encodes "slots_emitted:0" has been placed. | The authority cannot detect this collision — id validation is purely lexical. The id is a perfectly legal string but its *referent* is now a lie about the system's state. This is the literal Gödel construction: a sentence that, by being uttered, falsifies what it asserts. |

---

## 3. Totalizing claims that admit unprovable sentences

| Claim in code | Where | Sentence it cannot prove |
|---|---|---|
| "seq is GLOBAL" (I3 prose, `_log.reset` docstring) | `layout_authority_log.py:208–223` | "No client's `Last-Event-ID` collides with a post-reset seq." True only because the counter is monotone across resets — but the system has no *test* that fires if a future maintainer "fixes" the docstring's claimed bug by zeroing `_event_seq`. The invariant lives in prose, not in a guard. |
| "slot is FINAL" (I4, I7) | `layout_authority_protocol.py:201, 215` | "No `request_subtree` will emit a different `(x,y)` for an existing `node_id`." Geometry is deterministic, so this is true *in practice*. But the contract permits `request_subtree` to use a new domain anchor (if the domain registry's `_reserved` grew between the original placement and the resubmit) — and `_DomainRegistry` explicitly does *not* recompute prior anchors when reservation grows. So `(x,y)` *is* stable, but only by an invariant that itself is guarded by a comment ("frozen at first sighting"), not by an assertion. |
| "x,y is finite" (I1) | `layout_authority_protocol.py:184` | "No future geometry change will introduce NaN/inf." Verified at emission via `_validate_finite`, so the sentence is provable for emitted slots. But the invariant says "finite" without specifying the coordinate system; a client interpreting (x,y) as percentage of viewport vs. absolute pixels gets different downstream behavior. The system cannot prove its own coordinate semantics from the wire format alone. |
| "monotonic seq" (I2) | `layout_authority_protocol.py:187–191` | "Two SlotAssignments with the same `node_id` and different `seq` differ only because the later supersedes the earlier." Contradicted by G4: the geometry of the second is *identical* to the first by the FINAL invariant. The system cannot decide whether duplicate-seq-different-payload would be a bug or a feature, because the contract permits both readings. |

---

## 4. Recommendations (external verification, not internal patches)

The system cannot fix these from within. The fixes are external to the emission rules:

1. **Forbid id collisions with the counter vocabulary.** Add a validator that rejects `node_id` matching `^(seq|slots_emitted|edges_emitted|edges_dropped|pending_.+):` patterns. This closes G1 and G6 by *external lexical rule*, not by changing the protocol. (One-line check at the wire boundary.)
2. **Promote the single-producer rule from prose to a guard.** Track the producing thread's id in `_log` state; assert on every `emit()` that the caller matches. Closes G5 by making the precondition machine-checkable.
3. **Resolve I2 vs I4/I7 contradiction in the contract.** Either: (a) `request_subtree` re-emits with the *original* seq (violates I2 monotonicity) or (b) the slot is *not* FINAL (violates I4/I7). Pick one. Document the choice in an ADR. The current contract is inconsistent and clients reading I2 strictly will diverge from clients reading I4 strictly.
4. **`done` event must declare its own seq relation.** Add `final_seq: int` to the `done` payload (= `total_slots + total_edges + 1`, the seq of the done frame itself). Lets a client *prove* completeness from the wire alone instead of from prose.
5. **`replay_since` must distinguish "log empty" from "log lost your events".** Return a tagged variant: `Empty` (no emit since reset) vs `Lost` (since < oldest_seq - 1). Closes G3 by giving the SSE handler an unambiguous decision tree during the post-reset dead window.
6. **External audit by a different agent.** Per the second incompleteness theorem, the authority cannot prove its own consistency. A *different* implementation of the protocol (a consumer-side replay verifier that reconstructs the slot table from the wire and checks I1–I7) is the meta-system that catches what the producer cannot.

---

## 5. Hand-offs

- Contract-resolution ADR (recommendation 3) → **Lamport** (specification of the I2 vs I4/I7 reconciliation).
- Lexical id validator + producer-thread guard (recommendations 1, 2) → engineer.
- `final_seq` payload extension and `replay_since` tagged variant (recommendations 4, 5) → engineer + protocol owner.
- External wire-replay verifier (recommendation 6) → independent implementation, *not* by the team that wrote `layout_authority.py`.

---

## 6. The deepest sentence

> "This authority correctly emits every slot exactly once, in seq order, with FINAL coordinates, and the stream's totals match the log's newest seq."

This is the system's self-summary — the conjunction of I1–I7. It is *true* under single-producer, no-`request_subtree`, no-`reset`-mid-stream conditions. It is *not provable* from within the emission rules: the proof requires a meta-system that checks the wire output against the input deltas, and that meta-system does not exist in this codebase. The recommendation is not to patch the authority into self-provability (impossible — Gödel II) but to build the external verifier and accept that the authority's correctness is a claim made *to* a higher level, not *by* itself.
