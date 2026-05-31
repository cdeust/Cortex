# Nagarjuna Audit — Tetralemma on Slot Recomputation

> Method: catuskoti (four-cornered logic). For the question "should the layout
> authority recompute slots when domain count changes?", evaluate all four
> corners — yes, no, both, neither — then check whether the question itself
> is malformed. Strongest refutation = prasanga: take premises, show what
> they force. Sources: MMK Ch. 1–2; Priest 2010 §§2–3 (FDE).

---

## The decision under analysis

**P:** "When a new domain D arrives mid-build, the authority MUST recompute
all slot positions to rebudget against the new domain count."

**Surrounding texture (closed in prior audits):**
- I7 (Hart OT‑2, CLOSE): placeholder anchor for not-yet-emitted domain D =
  `domain_anchor(stable_index(D), N_CAP, cx, cy, base_r)`. Placeholder ==
  final modulo timing.
- N_CAP = 11 is a **conserved quantity** (Noether): the anchor formula is
  parameterised by N_CAP, not by live `len(domains_seen)`.
- Lavoisier flagged: I7 is not a count loss but a *value* loss if the
  placeholder differs from final.

---

## Corner 1 — P is true: recompute on every new-domain arrival

**Consequence:** the anchor formula becomes
`domain_anchor(index_of(D), len(domains_seen_now), cx, cy, base_r)`. Every
already-emitted slot is re-projected against a shrinking angular wedge. Slots
that were FINAL at t=k become NOT-FINAL at t=k+1.

**Prasanga:** the protocol's H3 (real domain emits at its slot far from the
cluster) and Hart OT‑2's "Placeholder == final modulo timing" both assume
slot positions are immutable once emitted. Recomputation contradicts the
premises that motivated I7's deterministic placeholder. If we recompute, I7
is unnecessary — there is no point computing a stable placeholder if the
real arrival rebudgets everything anyway.

**Verdict:** internally inconsistent with the closed texture. Refuted.

---

## Corner 2 — not-P: never recompute, slots stay where they were placed

**Consequence:** N_CAP = 11 is treated as a hard ceiling. Any project
arriving as the 12th, 13th, ... domain has no pre-allocated wedge. Either
(a) it is rejected, (b) it is given a fallback anchor that violates H3, or
(c) the system silently overflows.

**Prasanga:** Mendeleev's gap analysis (the empty-cell argument) says: a
periodic table that cannot accommodate undiscovered elements is not a
predictive theory but a fixed catalogue. A layout authority that cannot
seat domain #12 has the same defect. If N_CAP is a *fact about the
universe*, this corner is correct; if N_CAP is a *budget choice*, this
corner is brittle.

**Verdict:** correct only under the empirical claim that N_CAP ≥ all
domains that will ever arrive. Brittle if N_CAP is a guess.

---

## Corner 3 — both: recompute some kinds, not others

**Consequence:** distinguish two categories of "change":
1. **Identity-preserving:** the new domain D was already accounted for in
   N_CAP via `stable_index(D)`. Its slot was *already* reserved by I7's
   deterministic placeholder. Emission flips the slot from placeholder to
   real, but `(x, y)` does not move. **No recomputation needed — by
   construction, this is a no-op.**
2. **Capacity-changing:** the new domain D pushes `count > N_CAP`. The
   conserved quantity changes. This is not a mid-build recomputation but a
   **reseeding** of the protocol with new N_CAP'.

**Prasanga:** this corner shows the question conflates two phenomena. "A
new project arrives" is *not* a single event type. If `stable_index(D) <
N_CAP`, nothing recomputes because I7 already placed it. If `stable_index(D)
>= N_CAP`, the protocol's invariants no longer hold and we are in a
different regime entirely.

**Verdict:** this is the live answer. Both options are correct, in
different conditions.

---

## Corner 4 — neither: the question is malformed

**Consequence:** the question presupposes that "domain count" is an
intrinsic property whose change triggers a decision. But under the closed
I7 + Hart OT‑2 + Noether N_CAP texture, **`domain count` is not the
authority's input** — `stable_index(D)` and `N_CAP` are. The authority does
not know or care how many domains have *arrived*; it knows the *index* of
the one being emitted and the *cap* of the universe.

**Prasanga:** the framing "domain count changes" reifies an aggregate
(`len(domains_seen)`) that is not in the protocol's state. The protocol
operates on per-domain `stable_index(D)`, which is an immutable function
of `domain_id`. There is no "count change" event — only "domain D
emitted for the first time" events, which are deterministic projections,
not budget revisions.

**Verdict:** the question, as posed, treats a non-state quantity as if it
were state. Under the closed texture, the question is empty (sunya) of
referent.

---

## Reconciliation: protocol I7 vs Mendeleev gap analysis

**Apparent conflict.**
- I7 + Hart OT‑2: "no retroactive reseat" — placeholder == final, slots
  immutable.
- Mendeleev: "leave gaps for undiscovered elements" — the table must
  accommodate not-yet-seen domains.

**Dissolution (dependent origination).** The conflict is between two
*different* notions of "new":
- **New-to-the-session, known-to-N_CAP** (D such that `stable_index(D) <
  N_CAP`): I7 *is* Mendeleev's gap. The placeholder anchor is the empty
  cell. Emission fills the cell. No recomputation, no reseat — because the
  cell was reserved from t=0. Mendeleev and I7 agree.
- **New-to-N_CAP** (D such that `stable_index(D) >= N_CAP`): I7 has no
  cell for D. This is not a "domain count change"; it is a **change to the
  conserved quantity N_CAP itself**, which Noether's audit identifies as
  out-of-scope for I1–I7. Handling it requires a separate protocol
  (reseed-with-new-cap), not a mid-build recompute.

**Reconciled rule.**
1. Within `stable_index(D) < N_CAP`: I7 holds, Mendeleev satisfied, no
   recomputation. Question dissolves (Corner 4).
2. Across `stable_index(D) >= N_CAP`: out of scope for the current
   protocol. The right move is to (a) bound N_CAP empirically and prove
   coverage, or (b) define a new ceremony (Curie's carrier isolation:
   spawn a child cluster with its own (cx', cy', N_CAP') and link it to
   the parent). Not a recompute.

---

## Reification check & dependency network

| Concept | Essentialist reading | Dependent reading |
|---|---|---|
| "domain count" | scalar in protocol state | not in state — never read |
| "new domain arrives" | atomic event | two events: known-index emit vs cap overflow |
| "slot" | (x,y) intrinsic to D | derived from `(stable_index(D), N_CAP, cx, cy, base_r)` |

`slot(D)` depends on: `stable_index(D)` ← `domain_id` (immutable); `N_CAP`
(Noether-conserved); `(cx, cy, base_r)`. Does NOT depend on
`len(domains_seen)` or arrival order. "Recompute on count-change" is a
category error.

---

## Final answer

The correct corner is **(4) neither — the question is malformed**, with
**(3) both** as the operational gloss:

- For known-index domains: no recompute (I7 already placed them).
- For cap-overflow domains: not a recompute; a separate regime change.

The audits and Mendeleev's gap argument do not conflict — they answer
different questions. I7's "no retroactive reseat" is the *implementation*
of Mendeleev's "leave gaps." The conflict was an artifact of treating
"domain count" as protocol state when it is not.

---

## Hand-offs

- **Aristotle** — taxonomise "domain arrival events" into the two kinds
  above; encode as separate handler paths.
- **Curie** — design the carrier-isolation protocol for cap-overflow
  (child cluster, not parent recompute).
- **Popper** — falsifiability test: assert `forall D: slot(D, t1) ==
  slot(D, t2)` for all `t2 > t1` where `stable_index(D) < N_CAP`.
- **Lamport** — formalise N_CAP as protocol-level invariant; emission of
  D with `stable_index(D) >= N_CAP` MUST trap, never silently rebudget.
