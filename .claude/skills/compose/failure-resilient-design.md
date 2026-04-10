---
name: failure-resilient-design
description: >
  Design for failure: priority-displaced scheduling (hamilton), formal specification (lamport),
  implementation (engineer). The system degrades gracefully, not catastrophically.
category: compose
trigger: >
  When building a system that must survive overload, partial failure, or operator error;
  when the default failure mode is "crash" and needs to be "degrade"; when "what happens
  when everything goes wrong?" hasn't been answered.
agents:
  - hamilton
  - lamport
  - engineer
shapes: [hard-real-time, priority-under-failure, graceful-degradation, spec-first, partial-failure-default]
input: The system to harden. Its criticality requirements. Known failure modes.
output: Resilience design: criticality taxonomy, priority schedule, formal spec, implementation.
zetetic_gate:
  logical: "Criticality taxonomy must not contradict itself"
  critical: "Error paths must be tested to actually fire"
  rational: "Rigor proportional to criticality — Apollo for payments, not for marketing pages"
  essential: "The degraded state IS the design; it is not an afterthought"
composes: [design-for-failure, spec, implement]
aliases: [harden, resilience, design-for-failure]
hand_off:
  implementation_ready: "/implement — engineer builds it"
  needs_measurement: "/benchmark — verify the system actually degrades as designed"
---

## Procedure

### Phase 1: Design (hamilton)
1. hamilton: name the criticality tiers. What work is guaranteed (T0)? What is sheddable (T3)?
2. hamilton: design the priority-displaced schedule. Under overload, what is shed first?
3. hamilton: enumerate error paths. Each has a named behavior, a test, and a documented spec.
4. hamilton: design restart granularity. Task-level, not system-level.

### Phase 2: Specify (lamport)
5. lamport: write the spec. States, transitions, invariants. Include the failure model.
6. lamport: model-check on small instances. Counterexamples → revise the spec.
7. **Gate:** spec is clean on small instances and reviewed for omitted requirements.

### Phase 3: Implement (engineer)
8. engineer: implement per the spec. Every error path is a first-class code artifact with tests.
9. Chaos/fault-injection testing: verify the system actually degrades as designed under real failures.

## Output Format

```
## Failure-Resilient Design: [system]

### Criticality taxonomy:
| Tier | Definition | Examples | Shed policy |
|------|-----------|----------|-------------|

### Priority schedule: [under overload, what is shed in what order]
### Error paths: [each with named behavior + test]
### Spec: [invariants, transitions, failure model]
### Model-check: [instance size, results]
### Implementation: [files, tests, chaos test results]
```
