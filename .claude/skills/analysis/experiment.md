---
name: experiment
description: >
  Design and run a controlled experiment using Fisher's method: randomize, block, replicate,
  pre-specify the analysis. Design document written BEFORE the experiment runs.
category: analysis
trigger: >
  When a causal claim needs testing; when an A/B test needs design; when someone wants
  to "run it and see what happens" without a pre-specified plan.
agents:
  - fisher
  - experiment-runner
shapes: [randomize-to-eliminate-confounds, block-to-reduce-variance, replicate-to-estimate-variance, factorial-design, design-before-run]
input: A causal hypothesis to test. Available resources (users, machines, time).
output: Experimental design document with hypothesis, randomization, blocking, power calculation, analysis plan.
zetetic_gate:
  logical: "Design document exists BEFORE data collection"
  critical: "Randomized treatment assignment; confounds named and controlled"
  rational: "Power calculation matches expected effect size and available resources"
  essential: "Primary endpoint pre-specified; post-hoc analysis labeled as exploratory"
composes: []
aliases: [ab-test, controlled-experiment, design-experiment]
hand_off:
  results_in: "/benchmark — measure the outcome"
  confound_found: "/investigate — trace the confound"
---

## Procedure

1. **Hypothesis.** State the causal claim as a falsifiable proposition.
2. **Factors and levels.** What is varied? What is the control? What is blocked on?
3. **Randomization.** How are treatments assigned to units? (Random, stratified, blocked.)
4. **Power calculation.** Expected effect size → required sample size.
5. **Pre-specify analysis.** What test, what metric, what decision criterion. Written before data collection.
6. **Run.** Collect data per the design.
7. **Analyze per pre-specified plan.** Deviations labeled as exploratory.

## Output Format

```
## Experimental Design: [hypothesis]
### Factors: [treatment, control, blocking variables]
### Randomization: [method]
### Power: [effect size, baseline variance, required N]
### Primary endpoint: [metric, test, decision criterion]
### Confound audit:
| Confound | Controlled by | If not controlled |
|----------|---------------|-------------------|
```
