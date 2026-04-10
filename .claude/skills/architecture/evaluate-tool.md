---
name: evaluate-tool
description: >
  Evaluate a tool, technology, or framework with structured criteria, honest assessment,
  and protection against both cargo-culting and sunk-cost defense.
category: architecture
trigger: >
  When choosing between technologies; when evaluating whether to migrate from a current tool;
  when "everyone uses X" is the justification; when the current tool is being defended
  out of familiarity rather than merit.
agents:
  - hopper
  - engelbart
  - architect
  - feynman
shapes: [anticipate-obsolescence, cargo-cult-detector, augment-not-automate]
input: The tool(s) to evaluate. The use case. The current solution (if any).
output: Evaluation report with structured criteria, honest trade-offs, and recommendation.
zetetic_gate:
  logical: "Criteria defined before evaluation, not after"
  critical: "Evaluate against the use case, not against hype or familiarity"
  rational: "Include migration cost, not just destination merit"
  essential: "Recommend the tool that best serves the use case; defend no tool"
composes: [cargo-cult-check, verify-claim]
aliases: [evaluate, compare-tools, tech-choice]
hand_off:
  needs_experiment: "/experiment — run a controlled evaluation (spike, PoC)"
  migration_justified: "/refactor — plan the migration"
---

## Procedure

1. **Define criteria.** Before evaluating, list what matters: performance, ergonomics, ecosystem, maintainability, cost, team skill. Weight by the use case.
2. **hopper: obsolescence check.** Is the current tool defending position by merit or by sunk cost? Is a better abstraction clearly available?
3. **feynman: cargo-cult check.** Is the proposed tool recommended because "successful companies use it" without a causal mechanism?
4. **engelbart: augmentation check.** Does this tool augment the team's capability, or just automate a task? Which is needed?
5. **architect: structured comparison.** Score each option against the pre-defined criteria. Include migration cost.
6. **Honest trade-offs.** No option is all upside. Document the downsides of the recommendation.

## Output Format

```
## Tool Evaluation: [use case]
### Criteria (pre-defined):
| Criterion | Weight | Tool A | Tool B | Current |
|-----------|--------|--------|--------|---------|
### Cargo-cult check: [any tool recommended without mechanism?]
### Obsolescence check: [current tool defended by merit or sunk cost?]
### Migration cost: [if switching, what does it cost?]
### Recommendation: [tool, with honest trade-offs]
### Revisit when: [conditions that would change the recommendation]
```
