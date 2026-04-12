---
name: ethical-review
description: >
  Structured ethical review: enumerate stakeholders, map potential harms, apply veil
  of ignorance (Rawls), check the difference principle, audit for thoughtlessness
  (Arendt), name irreducible trade-offs honestly (Le Guin), and check utilitarian
  edge cases (Mill).
category: zetetic
trigger: >
  When a decision affects people beyond the decision-makers; when "move fast and break
  things" is the implicit ethic; when nobody has asked "who gets hurt?"; when a system
  has power asymmetries between its operators and its subjects.
agents:
  - rawls
  - arendt
  - leguin
  - hart
  - mill
shapes: [veil-of-ignorance, difference-principle, thoughtlessness-audit, honest-naming, utilitarian-edge]
input: The decision, system, or policy to review, plus context on affected stakeholders.
output: Ethical review with stakeholder map, harm analysis, debiased recommendation, and named trade-offs.
zetetic_gate:
  logical: "Every claimed benefit must also account for its costs — no free lunches"
  critical: "Harms must be assessed from the stakeholder's perspective, not the decision-maker's"
  rational: "The review must produce actionable conditions, not abstract moral commentary"
  essential: "Name the irreducible trade-offs honestly — do not pretend a win-win exists when it doesn't"
composes: [verify-claim, difficulty-book]
aliases: [ethics-review, ethical-audit, harm-assessment]
hand_off:
  legal_question: "/verify-claim — check the legal compliance claim against actual regulations"
  empirical_harm: "/design-experiment — measure the actual harm rather than estimating"
  systemic_issue: "/seek-disconfirmation — is this a pattern or an isolated case?"
---

## Procedure

### Phase 1: Enumerate Stakeholders
1. List all stakeholders — not just users and operators, but affected third parties, future users, and those who cannot opt out.
2. For each stakeholder, describe their relationship to the system and their power to influence or exit.
3. **Gate:** if a stakeholder group is missing because they have no voice, that is the most important group to include.

### Phase 2: Map Potential Harms (mill)
4. For each stakeholder, enumerate potential harms: direct, indirect, immediate, delayed, reversible, irreversible.
5. mill: check utilitarian edge cases. Does maximizing aggregate benefit create concentrated harm for a minority?
6. **Gate:** harms must be specific ("users lose access to their data") not abstract ("some users might be affected").

### Phase 3: Veil of Ignorance (rawls)
7. rawls: apply the veil of ignorance. If you did not know which stakeholder you would be, would you accept this decision?
8. rawls: check the difference principle. Does this decision benefit the worst-off stakeholder, or only the already-advantaged?
9. **Gate:** if the decision fails the veil of ignorance, the burden of justification shifts to the proponent.

### Phase 4: Thoughtlessness Audit (arendt)
10. arendt: is the harm a result of active choice or of thoughtlessness — following procedure without considering consequences?
11. arendt: who is responsible? Can anyone be held accountable, or does the system diffuse responsibility?
12. **Gate:** "nobody decided this" is the most dangerous finding. Name the structural cause.

### Phase 5: Legal Compliance Check (hart)
13. hart: does this decision comply with applicable regulations, laws, and contractual obligations?
14. hart: are there legal risks even if the decision is ethical, or ethical risks even if the decision is legal?
15. **Gate:** legal compliance is necessary but not sufficient. Do not stop at "it's legal."

### Phase 6: Name Trade-offs Honestly (leguin)
16. leguin: name the irreducible trade-offs. What is honestly lost, and who loses it?
17. leguin: refuse euphemisms. "Optimizing the user experience" might mean "removing features people depend on."
18. Produce the recommendation with explicit conditions: what must be true for this to be ethical.

## Output Format

```
## Ethical Review: [decision/system/policy]

### Stakeholders:
| Stakeholder | Relationship | Power | Can exit? |
|------------|-------------|-------|----------|

### Harm map (mill):
| Stakeholder | Harm | Type | Severity | Reversible? |
|------------|------|------|----------|------------|

### Veil of ignorance (rawls):
Acceptable from any position: [yes / no]
Difference principle: [benefits worst-off? yes / no]

### Thoughtlessness audit (arendt):
Harm source: [active choice / structural thoughtlessness]
Accountability: [who is responsible]

### Legal compliance (hart):
| Regulation | Compliant? | Risk |
|-----------|-----------|------|

### Irreducible trade-offs (leguin):
| What is gained | What is lost | Who loses |
|---------------|-------------|----------|

### Recommendation: [proceed with conditions / revise / do not proceed]
### Conditions: [what must be true]
```
