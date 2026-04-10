---
name: spec
description: >
  Write a formal specification for a concurrent or distributed protocol: states, transitions,
  invariants, failure model. Lamport method: spec before code.
category: architecture
trigger: >
  When building a concurrent/distributed system; when "it works on my machine" hides a race;
  when correctness is argued by example traces rather than invariants.
agents:
  - lamport
  - architect
shapes: [proof-before-code, invariants-not-traces, spec-first, partial-failure-default, distributed-causality]
input: The protocol or system to specify. Its correctness requirements.
output: Formal specification with states, transitions, invariants, failure model, and model-check results.
zetetic_gate:
  logical: "Invariants stated as predicates, not as example traces"
  critical: "Model-checked on small instances before any code is written"
  rational: "Spec covers the correctness-critical core, not the whole system"
  essential: "Spec is the minimum that makes correctness checkable"
composes: [contract]
aliases: [specify, write-spec, tla, formal-spec]
hand_off:
  spec_clean: "/implement — engineer builds code that refines the spec"
  counterexample_found: "Revise the spec; the counterexample is gold"
  needs_priority_design: "/design-for-failure — hamilton: priority scheduling under failure"
---

## Procedure

1. **lamport: scope.** Which part is correctness-critical? Only that part gets a spec.
2. **lamport: eliminate wall-clock.** Replace "when" with happens-before. State clock-skew assumptions explicitly.
3. **lamport: write the spec.** State variables, initial state, transitions, invariants.
4. **lamport: failure model.** Message loss, reorder, duplication, process crash, adversary.
5. **Model-check.** TLC on small instances (3-5 nodes). Find counterexamples.
6. **Iterate.** Fix counterexamples in the spec. Re-check. Repeat until clean.
7. **Challenge.** What would this spec miss? Have a non-author review it.

## Output Format

```
## Specification: [protocol/system]
### Scope: [correctness-critical component]
### State: [variables, initial]
### Transitions:
| Transition | Precondition | Effect |
|---|---|---|
### Invariants:
- I1: [...] — rationale
### Failure model: [message loss/reorder/duplication/crash]
### Causality: [happens-before, not wall-clock]
### Model-check: [instance size, invariants checked, counterexamples]
### Spec review: [omitted requirements considered]
```
