---
name: cargo-cult-check
description: >
  Detect cargo-cult practices — procedures followed because "successful people do it"
  without knowing the causal mechanism that makes them work.
category: zetetic
trigger: >
  When a practice is justified by "Google/Netflix/Stripe does it"; when a ceremony is
  performed without anyone being able to state what it produces; when a pattern is copied
  from a successful project without understanding why it succeeded.
agents:
  - feynman
shapes: [cargo-cult-detector]
input: >
  A practice, process, or technical choice to audit for cargo-cult status.
output: >
  Audit report: practice, stated justification, causal mechanism (or "missing"), verdict.
zetetic_gate:
  logical: "The causal mechanism must be statable and testable"
  critical: "No mechanism = cargo cult candidate, not confirmed cargo cult"
  rational: "If the ceremony stopped, what concretely would go wrong?"
  essential: "Only the mechanism justifies the practice; authority does not"
composes: [verify-claim]
aliases: [cargo-cult, ceremony-audit]
hand_off:
  mechanism_found: "Keep the practice on the basis of the mechanism"
  mechanism_missing: "Investigate further or abandon the practice"
  mechanism_disputed: "/verify-claim to check the mechanism"
---

## Purpose

Feynman's Move 3: when a procedure is being followed because "successful people do it," require the causal mechanism. No mechanism = the practice is a candidate cargo cult. The label is a diagnosis, not a dismissal — the practice may be real; the mechanism just hasn't been found yet.

## When to Use

- "We do standups because Google does standups."
- "We use microservices because Netflix uses microservices."
- "We add this boilerplate because the template includes it."
- A ceremony has been running for months and nobody can state what it produces.
- A technical pattern is being copied from a reference architecture without understanding the forces that produced it.

## Procedure

1. **Name the practice.** What exactly is being done?
2. **State the justification.** Why is it being done? (Usually: "X does it" or "best practice.")
3. **feynman agent asks: what is the causal mechanism?** What specific outcome does this practice produce that would not occur without it? If the caller can state the mechanism, verify it (/verify-claim). If not, the practice is a cargo cult candidate.
4. **The stop-test.** If this practice stopped tomorrow, what concretely would go wrong? If the answer is "nothing concrete" or "I'm not sure," the practice is cargo cult.
5. **Verdict.** Mechanism confirmed (keep) / Mechanism plausible but unverified (investigate) / No mechanism (abandon or investigate) / Mechanism disproved (abandon).

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Mechanism is statable | If not, it's a candidate |
| Critical | Mechanism is testable and tested | If untested, investigate |
| Rational | The stop-test has a concrete answer | If no concrete answer, it's cargo |
| Essential | Authority is not a mechanism | "Google does it" is not a mechanism |

## Output Format

```
## Cargo Cult Audit

| Practice | Justification | Causal mechanism | Stop-test answer | Verdict |
|----------|---------------|------------------|------------------|---------|
| [...] | [...] | [stated / missing] | [concrete / vague / none] | [keep/investigate/abandon] |
```

## Anti-patterns

- Labeling something "cargo cult" without specifying the missing mechanism (itself cargo-culted).
- Dismissing all ceremony as cargo cult (some ceremonies have real mechanisms).
- Accepting "it's best practice" as a mechanism.
- Keeping a practice after the mechanism has been disproved because "we've always done it."
