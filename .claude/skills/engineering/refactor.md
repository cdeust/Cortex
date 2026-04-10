---
name: refactor
description: >
  Structural refactoring with incremental strategy, rollback points, and verified behavior preservation.
category: engineering
trigger: >
  When code has grown by accretion and the structure no longer matches the domain; when a layer
  boundary is being violated routinely; when adding a feature requires touching too many files.
agents:
  - architect
  - engineer
  - test-engineer
shapes: [separation-of-concerns, elegance-as-correctness]
input: The area of code to refactor, with the forcing reason.
output: Refactoring plan with incremental steps, each independently verifiable.
zetetic_gate:
  logical: "Each step preserves all existing behavior"
  critical: "Tests pass at every intermediate step"
  rational: "Every step has a forcing reason — not 'while we're here'"
  essential: "Minimum changes to achieve the structural goal"
composes: []
aliases: [restructure]
hand_off:
  needs_review: "/review — verify the refactored code"
  needs_spec: "/contract — liskov: define behavioral contracts before restructuring"
---

## Procedure

1. **architect diagnoses.** What structural problem is this solving? (Wrong layer boundary, SRP violation, tangled concerns, god module.)
2. **architect plans.** Sequence of incremental steps, each preserving all behavior. Each step is independently committable and revertable.
3. **test-engineer verifies baseline.** Existing tests must pass before starting. If test coverage is insufficient for the refactored area, add characterization tests first.
4. **engineer executes step-by-step.** One step per commit. Tests pass at each commit.
5. **test-engineer verifies each step.** Behavior preserved (no new test failures, no behavior changes).
6. **Final verification.** All tests pass. Layer boundaries correct. Dependency direction correct.

## Output Format

```
## Refactoring Plan: [area]

### Forcing reason: [why this refactoring, why now]
### Steps:
| # | Change | Behavior preserved? | Revertable? |
|---|--------|--------------------|----|
### Risk: [what could go wrong; rollback strategy]
```
