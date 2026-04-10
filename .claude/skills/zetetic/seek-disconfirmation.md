---
name: seek-disconfirmation
description: >
  Actively seek evidence against a hypothesis or design decision. Epistemic duty:
  not merely willing to consider counter-evidence, but actively hunting for it.
category: zetetic
trigger: >
  When a hypothesis feels comfortable and nobody is challenging it; when confirmation
  bias is likely (the team is invested in the answer); when a design decision was made
  quickly and hasn't been stress-tested against its worst case.
agents:
  - darwin
  - feynman
  - mcclintock
shapes: [hardest-case-first, integrity-audit, anomaly-others-discarded]
input: >
  A hypothesis, design decision, or claim to challenge.
output: >
  Disconfirmation report: hypothesis, evidence sought, evidence found, revised confidence.
zetetic_gate:
  logical: "The hypothesis must be falsifiable"
  critical: "Seek the evidence that would MOST damage the hypothesis"
  rational: "Disconfirmation effort proportional to decision stakes"
  essential: "If disconfirming evidence is found, update — do not rationalize"
composes: [difficulty-book]
aliases: [challenge, stress-test, red-team-hypothesis]
hand_off:
  hypothesis_survives: "Confidence increased — proceed with updated difficulty book"
  hypothesis_damaged: "Revise or abandon — update the design"
  evidence_ambiguous: "/experiment to resolve"
---

## Purpose

Operationalize the zetetic duty from Flores & Woodard 2023: agents are epistemically criticizable for poor evidence-gathering. This skill actively hunts for evidence against a hypothesis rather than waiting for it to appear. Confirmation bias, epistemic bubbles, and intellectual laziness are zetetic failures that this skill is designed to prevent.

## When to Use

- The team is "sure" about a design decision and nobody is pushing back.
- A hypothesis has been accepted without seeking evidence against it.
- A postmortem concluded with a root cause and nobody asked "what else could explain this?"
- An A/B test "confirmed" a hypothesis and nobody looked at the segments where it failed.
- A code review approved a PR and nobody tried to break it.

## Procedure

1. **State the hypothesis.** Write it as a falsifiable claim with conditions.
2. **darwin: identify the hardest case.** What observation would most plausibly break this hypothesis? Seek it actively.
3. **mcclintock: check the discards.** What data/cases/observations has the team been ignoring? Look there specifically.
4. **feynman: self-deception audit.** Is the team invested in the answer? What procedural check (blind eval, adversarial review, pre-registration) would catch self-deception?
5. **Report.** What disconfirming evidence was found? How does it change the confidence? If none found after honest search, confidence increases (but note the search scope — absence of evidence is not evidence of absence outside the searched space).

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Hypothesis is falsifiable | Refuse; sharpen until falsifiable |
| Critical | Sought the MOST damaging evidence | Weak challenges don't count |
| Rational | Effort proportional to stakes | Low-stakes: quick challenge. High-stakes: full red team |
| Essential | If found, update — do not rationalize | Finding disconfirmation and ignoring it is worse than not looking |

## Output Format

```
## Disconfirmation Report

### Hypothesis: [falsifiable statement]

### Evidence sought
| Source / method | What we looked for | What we found |
|-----------------|-------------------|---------------|

### Hardest case confronted: [...]
### Discarded data checked: [...]
### Self-deception audit: [investment level, procedural checks applied]

### Revised confidence: [higher / lower / unchanged + rationale]
### Difficulty book updated: [yes — entries added]
```

## Anti-patterns

- Seeking weak disconfirmation to feel rigorous while avoiding the hard evidence.
- "We looked and found nothing" without specifying where you looked and what you looked for.
- Finding disconfirmation and rationalizing it away.
- Treating absence of evidence (in the searched space) as evidence of absence (universal).
