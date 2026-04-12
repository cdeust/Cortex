---
name: design-experiment
description: >
  Design a controlled experiment using Fisher's method. Alias for /experiment with research framing.
category: research
trigger: >
  When a research hypothesis needs testing; when an ablation study needs design;
  when hyperparameter search needs structure.
agents:
  - fisher
  - experiment-runner
shapes: [randomize-to-eliminate-confounds, factorial-design, design-before-run]
input: Research hypothesis. Available resources (compute, data, time).
output: Experimental design document with ablation plan, controls, power calculation.
zetetic_gate:
  logical: "Design exists before the experiment runs"
  critical: "Randomized, with controls and replication"
  rational: "Power calculation matches the expected effect size"
  essential: "Primary metric pre-specified; post-hoc analysis labeled exploratory"
composes: [experiment]
aliases: [ablation-design, experiment-design]
hand_off:
  results_ready: "/benchmark — measure the outcome"
  paper_ready: "/write-paper — write up the results"
---

## Procedure

Same as `/experiment` (see skills/analysis/experiment.md) with research-specific additions:

1. **Ablation plan.** Which components are being ablated? Each ablation is a factor in a factorial design.
2. **Baseline.** What is the reference configuration? All comparisons are relative to the baseline.
3. **Random seeds.** Each configuration runs on N seeds. Seed is a blocking variable.
4. **Pre-registration.** The experimental design is documented before any runs. Post-hoc analyses are labeled.
5. **Negative results.** Negative results are findings, not failures. Document them with equal rigor.
6. **Compute environment.** Specify the execution environment:
   - Apple Silicon local: `tools/mlx-compute.sh check` to verify, `tools/mlx-compute.sh benchmark` to run.
   - Docker isolation: `tools/docker-runner.sh build` for reproducible environment, `tools/docker-runner.sh run` to execute.

## Output Format

```
## Experiment Design: [hypothesis]
### Ablation factors:
| Factor | Levels | Baseline level |
|--------|--------|---------------|
### Design: [full factorial / fractional / one-at-a-time — justify]
### Seeds: [N per configuration]
### Power: [expected effect → required runs]
### Pre-registered metric: [what, how measured]
### Negative-result protocol: [documented with equal rigor]
```
