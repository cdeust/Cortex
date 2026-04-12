---
name: argument-construction
description: >
  Build a structured argument: Toulmin model for structure, Aristotle for audience
  calibration, Feynman for integrity audit, Kahneman for debiasing.
category: compose
trigger: >
  When a proposal needs to persuade stakeholders; when an argument is being made
  informally and needs rigor; when a technical recommendation must survive scrutiny
  from diverse audiences.
agents:
  - toulmin
  - aristotle
  - feynman
  - kahneman
shapes: [claim-evidence-warrant, ethos-pathos-logos, lean-over-backwards, debias]
input: The claim to argue for, the target audience, and the available evidence.
output: Structured argument with claim, evidence, warrants, qualifiers, rebuttals, and integrity audit.
zetetic_gate:
  logical: "Warrant must connect evidence to claim without logical gaps"
  critical: "Evidence must be verified — no invented or unverified data in the argument"
  rational: "Argument must be calibrated to the audience without sacrificing accuracy"
  essential: "State the strongest counterargument and address it — do not straw-man"
composes: [verify-claim]
aliases: [build-argument, persuade, make-case, argue]
hand_off:
  evidence_missing: "/literature-review — find the evidence the argument needs"
  claim_unverifiable: "/verify-claim — check the core claim before building on it"
  audience_unknown: "(pause) — audience must be specified before structuring"
---

## Procedure

### Phase 1: Identify the Claim and Evidence
1. State the claim clearly as a single proposition.
2. Gather all available evidence. Each piece of evidence must be sourced and verified.
3. **Gate:** evidence must be real. No fabricated data, no unverified statistics, no "studies show."

### Phase 2: Toulmin Structure (toulmin)
4. toulmin: articulate the warrant — the principle that connects evidence to claim.
5. toulmin: add backing — what supports the warrant itself?
6. toulmin: add qualifier — under what conditions and with what confidence does the claim hold?
7. toulmin: state the rebuttal — what would make the claim false? Address it.
8. **Gate:** the rebuttal must be the strongest available counterargument, not a straw-man.

### Phase 3: Audience Calibration (aristotle)
9. aristotle: ethos — what credibility grounds this argument? (expertise, track record, data)
10. aristotle: logos — is the logical structure clear to this specific audience?
11. aristotle: pathos — what does the audience care about? Connect without manipulating.
12. **Gate:** persuasion must not distort the claim. Calibrate presentation, not substance.

### Phase 4: Integrity Audit (feynman, kahneman)
13. feynman: lean-over-backwards test. Are you reporting the evidence that argues against you?
14. kahneman: check for confirmation bias, anchoring, availability bias in the evidence selection.
15. **Gate:** if the integrity audit finds suppressed counterevidence, revise the argument.

## Output Format

```
## Argument: [claim]

### Toulmin structure:
| Element | Content |
|---------|---------|
| Claim | [...] |
| Evidence | [...] |
| Warrant | [...] |
| Backing | [...] |
| Qualifier | [...] |
| Rebuttal | [...] |

### Audience calibration (aristotle):
Audience: [who]
Ethos: [...] | Logos: [...] | Pathos: [...]

### Integrity audit:
Lean-over-backwards (feynman): [pass / fail — what was found]
Bias check (kahneman): [biases detected and corrected]

### Final argument: [structured narrative]
```
