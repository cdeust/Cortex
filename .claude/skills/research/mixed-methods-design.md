---
name: mixed-methods-design
description: >
  Design a mixed-methods study: determine mixing strategy, design quantitative strand
  (Fisher), design qualitative strand (Strauss/Geertz), specify integration points,
  and produce a unified protocol.
category: research
trigger: >
  When a research question requires both quantitative and qualitative evidence; when
  numbers alone miss the mechanism and narratives alone miss the prevalence; when
  "mixed methods" is planned but the integration strategy is unspecified.
agents:
  - fisher
  - strauss
  - geertz
  - varela
  - eco
shapes: [convergent-design, explanatory-sequential, exploratory-sequential, integration-point]
input: Research question, available data types, and constraints on data collection.
output: Mixed-methods protocol with strand designs, mixing strategy, and integration specification.
zetetic_gate:
  logical: "Each strand must be methodologically sound on its own before integration"
  critical: "Integration points must be specified — not 'we'll combine them later'"
  rational: "Mixing strategy must match the research question, not a default preference"
  essential: "Mixed methods is justified only when neither strand alone suffices — verify this"
composes: [research-question-formulation, design-experiment]
aliases: [mixed-methods, qual-quant, multi-method]
hand_off:
  quant_only_suffices: "/design-experiment — single quantitative design is sufficient"
  qual_only_suffices: "/qualitative-analysis — single qualitative design is sufficient"
  integration_unclear: "(iterate) — specify exactly how and when strands connect"
---

## Procedure

### Phase 1: Justify Mixed Methods
1. State the research question. Why does it require both quantitative and qualitative evidence?
2. **Gate:** if one strand alone suffices, do not use mixed methods. Redirect to the appropriate skill.

### Phase 2: Determine Mixing Strategy
3. Choose the mixing strategy based on the research question:
   - **Convergent**: both strands collected simultaneously, merged during interpretation. Use when seeking corroboration.
   - **Explanatory sequential**: quantitative first, then qualitative to explain the numbers. Use when patterns need mechanism.
   - **Exploratory sequential**: qualitative first, then quantitative to test generalizability. Use when the phenomenon is poorly understood.
4. **Gate:** the mixing strategy must be justified by the question, not by convenience.

### Phase 3: Design Quantitative Strand (fisher)
5. fisher: define variables, sample, measurement instruments, and analysis plan.
6. fisher: specify statistical tests and power analysis.
7. **Gate:** the quantitative strand must be valid independently.

### Phase 4: Design Qualitative Strand (strauss, geertz, varela)
8. Choose the qualitative approach:
   - strauss: grounded theory — when building theory from data.
   - geertz: thick description — when context and meaning are central.
   - varela: first-person data — when subjective experience is part of the phenomenon.
9. Design sampling, data collection, and analysis procedures for the chosen approach.
10. **Gate:** the qualitative strand must be valid independently.

### Phase 5: Specify Integration (eco)
11. eco: define the integration points — where, when, and how the strands connect.
12. eco: specify what the integrated analysis produces that neither strand alone could.
13. Design the joint display: the artifact that shows integrated findings.

### Phase 6: Unified Protocol
14. Produce the unified protocol with timeline, responsibilities, and quality criteria for each strand and the integration.

## Output Format

```
## Mixed-Methods Design: [research question]

### Justification: [why mixed methods is necessary]
### Mixing strategy: [convergent / explanatory-sequential / exploratory-sequential]

### Quantitative strand (fisher):
Variables: [...] | Sample: [...] | Analysis: [...]

### Qualitative strand ([approach]):
Sampling: [...] | Collection: [...] | Analysis: [...]

### Integration (eco):
| Integration point | What connects | What it produces |
|-------------------|--------------|-----------------|

### Joint display: [description of the integrated artifact]

### Timeline:
| Phase | Strand | Duration | Deliverable |
|-------|--------|----------|------------|
```
