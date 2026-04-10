---
name: statistical-intervention
description: >
  Full pipeline for data-driven organizational change: detect the statistical anomaly
  (semmelweis), design the experiment (fisher), integrity-check the result (feynman).
category: compose
trigger: >
  When two matched groups have different outcomes and nobody has investigated why;
  when a proposed change has data support but faces institutional resistance;
  when "we've always done it this way" is blocking an evidence-backed improvement.
agents:
  - semmelweis
  - fisher
  - feynman
shapes: [statistical-anomaly-between-groups, design-before-run, integrity-audit, semmelweis-reflex-awareness]
input: Two groups with different outcomes, or a proposed intervention with data.
output: Full pipeline: matched-group analysis, experimental design, intervention results, communication plan.
zetetic_gate:
  logical: "Matched groups must be truly matched except for the candidate variable"
  critical: "Before/after data with the intervention as the only change"
  rational: "The communication plan is as important as the data"
  essential: "Data + bad communication = zero impact (the Semmelweis lesson)"
composes: [experiment, audit-integrity]
aliases: [data-driven-change, matched-group-analysis]
hand_off:
  intervention_works: "Communicate + implement per the plan"
  intervention_fails: "The candidate cause was wrong — investigate further"
  institutional_resistance: "Route around with stakeholder-aware communication (semmelweis Move 3)"
---

## Procedure

### Phase 1: Detect (semmelweis)
1. semmelweis: compare matched groups. What is the same? What differs? The difference is the candidate cause.
2. semmelweis: design the cheapest intervention that tests the hypothesis.
3. semmelweis: collect before-data NOW, before intervening.

### Phase 2: Test (fisher)
4. fisher: design the experiment properly. Randomize if possible; at minimum, control for confounds.
5. Run the intervention. Collect after-data.
6. fisher: analyze per the pre-specified plan.

### Phase 3: Verify (feynman)
7. feynman: integrity audit. List what could invalidate the result. Check for self-deception.
8. feynman: alternative explanations. Is there another cause that explains the data?

### Phase 4: Communicate (semmelweis)
9. semmelweis: plan the communication. Stakeholders, incentives, objections, allies.
10. semmelweis: anticipate the Semmelweis reflex. Route around it — do not confront with more data.

## Output Format

```
## Statistical Intervention: [problem]

### Matched groups: [what's same, what differs]
### Intervention: [what was done]
### Before/after:
| | Group A | Group B (control) |
|---|---|---|
| Before | [...] | [...] |
| After | [...] | [...] |
### Integrity check: [what could invalidate? alternative explanations?]
### Communication plan:
- Stakeholders: [...]
- Anticipated resistance: [...]
- Route-around strategy: [...]
```
