---
name: audit-integrity
description: >
  Integrity audit of a claimed result: check for self-deception, cargo cults, missing
  limitations, and untested assumptions. Feynman's "lean over backwards" discipline.
category: analysis
trigger: >
  When a result feels too clean; when nobody has listed what could invalidate it;
  when the team is strongly invested in the conclusion; when a presentation has no
  limitations section.
agents:
  - feynman
  - darwin
shapes: [integrity-audit, cargo-cult-detector, difficulty-book, sum-over-histories]
input: A result, claim, or conclusion to audit.
output: Integrity report with rederivation gaps, cargo cult candidates, high-impact limitations, alternative explanations.
zetetic_gate:
  logical: "Can the result be rederived from premises without consulting the original?"
  critical: "Are the highest-impact potential invalidators listed?"
  rational: "Is the team's investment in the conclusion creating bias?"
  essential: "The honest summary: what is known, what is uncertain, what was missed"
composes: [verify-claim, cargo-cult-check, seek-disconfirmation]
aliases: [integrity-check, self-deception-audit]
hand_off:
  gap_found: "/rederive — feynman: close the understanding gap"
  claim_unsupported: "/verify-claim — find the sources"
  result_contested: "/experiment — fisher: design a test to resolve"
---

## Procedure

1. **Rederivation.** feynman: for each load-bearing claim, attempt rederivation from premises. Note where it fails.
2. **Plain-language check.** Can each technical claim be explained without jargon? Jargon gaps = understanding gaps.
3. **Cargo cult scan.** For each procedure followed: what is the causal mechanism?
4. **Limitations.** List everything that could invalidate the result. Rank by "how much would this hurt?"
5. **Alternative explanations.** Enumerate all plausible alternatives. The answer is where multiple lines converge.
6. **Self-deception check.** Is anyone strongly invested in this being true? What procedural check applies?

## Output Format

```
## Integrity Audit: [result]

### Rederivation: [gaps found]
### Cargo cult scan: [mechanisms missing]
### Limitations (ranked by damage):
1. [highest impact] — status
2. ...
### Alternative explanations:
| Alternative | Supporting evidence | Incompatible evidence |
|---|---|---|
### Self-deception risk: [high/medium/low] — checks applied: [...]
### Honest summary: known / uncertain / missed
```
