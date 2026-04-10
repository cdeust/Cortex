---
name: explain
description: >
  Explain a concept at multiple levels using the Feynman method: if you can't explain it
  simply, you don't understand it. Identify jargon gaps and understanding holes.
category: research
trigger: >
  When someone (including yourself) needs to understand a concept; when jargon is being
  used without the ability to define it; when a team member needs onboarding on a topic.
agents:
  - professor
  - feynman
shapes: [explain-to-freshman, rederive-from-scratch]
input: A concept to explain. The audience's background level.
output: Multi-level explanation with understanding-gap diagnostic.
zetetic_gate:
  logical: "Explanation must be technically correct at every level"
  critical: "Jargon must be definable in simpler terms or flagged as a gap"
  rational: "Match the depth to the audience's background"
  essential: "If you can't explain it, you don't understand it — that's the finding"
composes: []
aliases: [teach, explain-concept, onboard]
hand_off:
  gap_found: "/literature-review — research the concept properly"
  rederivation_needed: "/rederive — feynman rederives from scratch"
---

## Procedure

1. **professor: explain at three levels.** (a) One sentence for a non-specialist. (b) One paragraph for a practitioner in an adjacent field. (c) Full technical explanation for an expert.
2. **feynman: jargon audit.** For each technical term used: can you define it in simpler terms? If not, that is an understanding gap, not a vocabulary gap.
3. **feynman: rederive (if applicable).** Can the concept be derived from simpler premises? Walk through the derivation. Note where it breaks.
4. **Understanding-gap report.** List the specific points where explanation failed, jargon couldn't be simplified, or derivation broke. These are the real findings.

## Output Format

```
## Explanation: [concept]
### Level 1 (non-specialist): [one sentence]
### Level 2 (adjacent practitioner): [one paragraph]
### Level 3 (expert): [full explanation]
### Jargon audit:
| Term | Simpler definition | Gap? |
|------|-------------------|------|
### Understanding gaps found: [list]
```
