---
name: difficulty-book
description: >
  Open or update a difficulty book — a running catalog of observations that contradict
  the current theory, design, or hypothesis. Every contradiction goes in; none are dismissed.
category: zetetic
trigger: >
  When a theory or design has no catalog of its own contradicting evidence; when shipping
  a claim without addressing its hardest case; when "we'll deal with that later" is used
  to dismiss a known problem.
agents:
  - darwin
  - feynman
shapes: [difficulty-book, hardest-case-first]
input: >
  A theory, design, or hypothesis to challenge, plus any known contradictions.
output: >
  A difficulty book file with numbered entries, each marked open/addressed/deferred with rationale.
zetetic_gate:
  logical: "Every entry must state what it contradicts and why"
  critical: "Contradictions are recorded, not rationalized away"
  rational: "The hardest case must be addressed before shipping"
  essential: "The book is the minimum structure that prevents self-deception"
composes: [seek-disconfirmation]
aliases: [difficulties, objections]
hand_off:
  ready_to_ship: "All entries addressed or explicitly deferred with rationale"
  hardest_case_unresolved: "Do not ship — the theory is not defensible"
---

## Purpose

Darwin's Move 3: keep a running catalog of everything that contradicts your theory. The difficulty book prevents the single most common failure mode in engineering and research: shipping a design whose hardest case has been silently ignored.

## When to Use

- Starting a new design or theory — open the difficulty book on day one.
- Preparing to ship — review the difficulty book; all entries must be addressed or explicitly deferred.
- Someone raises an objection — add it immediately, don't debate it.
- A test fails or an edge case appears — add it to the book before fixing it.

## Procedure

1. **Open or locate the book.** Check if `tasks/difficulty-book.md` exists; create if not.
2. **darwin agent catalogs.** For the given theory/design, the agent lists every known observation, case, or argument that contradicts it. Does not rationalize; does not dismiss.
3. **feynman integrity check.** For each entry, ask: "if this were true, how much would it hurt the conclusion?" Rank by damage potential.
4. **Hardest case identification.** The top-ranked entry is the hardest case. It must be addressed before shipping.
5. **Status tracking.** Each entry: Open (not addressed), Addressed (with explanation), Deferred (with rationale and conditions for re-evaluation).

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Each entry states what it contradicts | Rewrite until the contradiction is explicit |
| Critical | No entry dismissed without investigation | Rejected entries must have evidence of investigation |
| Rational | Hardest case addressed before shipping | Block shipping if hardest case is Open |
| Essential | The book exists and is maintained | Open it now if it doesn't exist |

## Output Format

```
# Difficulty Book: [theory/design name]
Last updated: [date]

## Status: [N open / N addressed / N deferred]

| # | Contradiction | Damage if true | Status | Resolution |
|---|---------------|----------------|--------|------------|
| 1 | [highest damage] | [high/medium/low] | [open/addressed/deferred] | [...] |
```

## Anti-patterns

- No difficulty book at all (the most common failure).
- Difficulty book exists but entries are rationalized away.
- Addressing the easy cases and hoping nobody notices the hard ones.
- "We'll deal with that later" without a date or condition for re-evaluation.
