---
name: benchmark
description: >
  Benchmark a change with before/after measurement, statistical comparison, and
  no-regression guarantee.
category: analysis
trigger: >
  When a code change claims to improve performance; when a regression must be detected;
  when "it feels faster" is the evidence.
agents:
  - curie
  - engineer
  - fisher
shapes: [instrument-before-hypothesis, two-independent-methods, replicate-to-estimate-variance]
input: The change to benchmark. The metric. The target.
output: Before/after comparison with statistical confidence, regression check, verdict.
zetetic_gate:
  logical: "Same conditions for before and after"
  critical: "Multiple runs with statistical comparison, not a single run"
  rational: "No regression on any metric; improvement on the target metric"
  essential: "Benchmark the change in isolation — no other variables"
composes: []
aliases: [bench, perf-test]
hand_off:
  regression_found: "/debug — trace the regression to its root cause"
  no_improvement: "/optimize — profile to find the actual bottleneck"
---

## Procedure

1. **curie: instrument.** Define the metric, the measurement procedure, and the noise floor.
2. **fisher: design.** Same hardware, same data, same load. Multiple runs (N ≥ 5). Randomize run order.
3. **Measure before.** N runs of the baseline. Record mean, std, distribution.
4. **Apply the change.** Nothing else changes.
5. **Measure after.** N runs of the changed version. Same conditions.
6. **Compare.** Statistical test (paired t-test or Wilcoxon if non-normal). Effect size. Confidence interval.
7. **Regression check.** ALL metrics, not just the target. Any regression blocks the change.

## Output Format

```
## Benchmark: [change description]
### Metric: [what, units]
### Conditions: [hardware, data, load]
### Results:
| | Before (mean ± std) | After (mean ± std) | Change | p-value | CI |
|---|---|---|---|---|---|
### Regression check: [all other metrics stable? yes/no]
### Verdict: [improved / no change / regressed]
```
