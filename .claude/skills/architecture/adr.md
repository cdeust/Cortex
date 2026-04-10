---
name: adr
description: >
  Write an Architecture Decision Record: context, options considered, decision, consequences,
  and what would trigger revisiting.
category: architecture
trigger: >
  When a significant technical decision is being made; when "why did we choose X?" has
  no documented answer; when a decision needs to survive team turnover.
agents:
  - architect
  - darwin
shapes: [difficulty-book]
input: The decision to be made, with context and constraints.
output: ADR document following the standard template.
zetetic_gate:
  logical: "All options considered must be listed, not just the chosen one"
  critical: "Trade-offs documented honestly — no option is all upside"
  rational: "Decision justified by the specific context, not by abstract 'best practice'"
  essential: "Includes the trigger for revisiting — when would this decision become wrong?"
composes: [difficulty-book]
aliases: [architecture-decision, decision-record]
hand_off:
  decision_needs_data: "/estimate — fermi bounds the key quantity"
  decision_needs_experiment: "/experiment — fisher tests the hypothesis"
---

## Procedure

1. **architect: state the context.** What problem does this decision solve? What constraints exist?
2. **architect: enumerate options.** All viable alternatives, including "do nothing."
3. **darwin: difficulty-book each option.** For each option, list the observations that argue against it.
4. **architect: decide.** State the chosen option with rationale. The rationale must reference the specific context, not generic "best practice."
5. **Consequences.** What follows from this decision? What becomes easier? What becomes harder?
6. **Revisit trigger.** Under what conditions would this decision become wrong? (Changed scale, new technology, team change.)

## Output Format

```
# ADR-[number]: [title]
## Status: [Proposed / Accepted / Deprecated / Superseded]
## Context: [what problem, what constraints]
## Options considered:
| Option | Pros | Cons | Difficulty-book entries |
|--------|------|------|----------------------|
## Decision: [chosen option]
## Rationale: [why this option given THIS context]
## Consequences: [what follows]
## Revisit when: [trigger conditions]
```
