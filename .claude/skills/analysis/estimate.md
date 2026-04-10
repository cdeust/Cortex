---
name: estimate
description: >
  Bracket a quantity to order-of-magnitude using Fermi decomposition. Two-sided bound
  with dominant uncertainty identified and next measurement recommended.
category: analysis
trigger: >
  When a decision is blocked by "we don't have data"; when a number is cited without
  cross-check; when false precision is masking bad assumptions.
agents:
  - fermi
shapes: [order-of-magnitude-first, bracket-before-solve, refuse-false-precision, feasibility-bound]
input: A quantity to estimate, with context about the decision it feeds. Units required.
output: >
  Decomposition table, primary bracket, cross-check bracket, dominant uncertainty,
  model assumptions, decision implication, next measurement recommendation.
zetetic_gate:
  logical: "Decomposition must be dimensionally consistent"
  critical: "Two independent decompositions must agree to x10"
  rational: "Bracket today beats precise number next quarter"
  essential: "Refine only the dominant uncertainty"
composes: []
aliases: [bound-quantity, fermi-estimate]
hand_off:
  tight_bracket: "/isolate-signal — curie measures precisely"
  mechanism_needed: "/rederive — feynman explains why"
  kills_the_idea: "(stop) — no further work needed"
---

## Procedure

1. **Frame.** State the quantity with units. No units = no estimate.
2. **Decompose.** 4-8 independent factors, each bracketable from anchors or memory.
3. **Bracket.** Low and high for each factor. Multiply to produce the primary bracket.
4. **Cross-check.** Second, independent decomposition. Must agree to x10.
5. **Dominant uncertainty.** The widest-bracketed factor. All further work targets this.
6. **Decision implication.** If HIGH < threshold: kill. If LOW > threshold: proceed. If straddles: measure the dominant factor.

## Output Format

```
## Fermi Estimate: [quantity, units]
### Decomposition
| Factor | Low | High | Anchor |
|--------|-----|------|--------|
### Bracket: [low-product] — [high-product]
### Cross-check: [second decomposition result] — agrees to x[N]
### Dominant uncertainty: [factor] because [reason]
### Decision: [kill / proceed / measure dominant factor]
### Next measurement: [what to measure to tighten the bracket]
```
