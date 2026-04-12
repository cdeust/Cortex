---
name: autoresearch-loop
description: >
  Automated optimize-measure-iterate research loop. Define an objective function,
  establish a baseline, then cycle through hypothesis-implement-benchmark-decide until
  diminishing returns are detected. Every iteration produces a git commit and a lab
  notebook entry. The loop maintains a leaderboard of all attempts.
category: research
trigger: >
  When optimizing a metric iteratively; when "try things and see what works" needs
  structure; when a research question maps to a measurable objective function;
  when manual optimize-measure cycles are too slow or too sloppy.
agents:
  - peirce
  - fisher
  - curie
  - laplace
  - schon
  - deming
  - darwin
  - shannon
shapes: [instrument-before-hypothesis, two-independent-methods, replicate-to-estimate-variance]
input: Objective function (metric + direction). Codebase path. Max iterations. Stopping criteria.
output: Leaderboard of attempts. Best-known configuration merged to main. Lab notebook with full history.
zetetic_gate:
  logical: "Objective function is well-defined and monotonic in the desired direction"
  critical: "Baseline is measured before any change; same conditions for every iteration"
  rational: "Each iteration changes exactly one variable — no confounded experiments"
  essential: "Diminishing returns are detected and the loop stops; no infinite tinkering"
composes: [benchmark, lab-notebook]
aliases: [research-loop, optimize-loop, iterate]
hand_off:
  stuck_no_improvement: "/deep-research — literature review for new hypotheses"
  regression_found: "/debug — trace the regression to root cause before continuing"
  diminishing_returns: "/explain — write up the findings and publish"
---

## Procedure

### Phase 0: Define (shannon + curie)

1. **shannon: define the objective function.** What metric? What units? What direction is better?
   Information-theoretic grounding: is the metric measuring what we think it measures?
2. **curie: instrument.** How is the metric measured? What is the noise floor? What is the
   measurement variance? Establish the minimum detectable effect size.

### Phase 1: Baseline

3. **Measure current state.** N >= 5 runs under controlled conditions. Record mean, std, distribution.
4. **Commit as baseline.** `git commit` with message: `baseline: [metric] = [value +/- std]`.
5. **Lab notebook entry.** Record: objective, measurement procedure, baseline result, conditions.

### Phase 2: Iterate (loop starts here)

6. **peirce: generate hypothesis.** Given the current best-known result and all prior attempts
   (including failures), what single change is most likely to improve the metric? Abductive
   reasoning: what would explain the current performance gap?
7. **fisher: design the experiment.** Same conditions as baseline. Single variable changed.
   Randomized run order. N >= 5 runs. Pre-register the expected direction and effect size.
8. **Implement the change.** Create a branch. Make the modification. Keep it minimal.
9. **Commit the change.** `git commit` with message linking to the hypothesis:
   `hypothesis: [description] — expected [direction] on [metric]`.
10. **curie: run benchmark.** Execute the same measurement procedure as baseline. Same N, same conditions.
    Use `tools/mlx-compute.sh benchmark` for Apple Silicon ML experiments or
    `tools/docker-runner.sh run` for isolated reproducible environments.
11. **laplace: Bayesian comparison.** Prior: previous iterations' results. Likelihood: current data.
    Posterior: probability that this change is an improvement. Report: posterior probability,
    credible interval, Bayes factor.
12. **Decide: keep or revert.**
    - If better (posterior p(improvement) > 0.9 AND effect > noise floor): merge to main,
      update best-known. `git merge` with message: `improvement: [metric] [old] -> [new] (+X%)`.
    - If worse or within noise: revert. `git revert` with message:
      `revert: [hypothesis] — no improvement ([result])`.
    - Log negative result either way.
13. **darwin: difficulty book entry.** If the result was surprising (contradicted the hypothesis),
    record in the difficulty book. What was expected? What happened? What does this teach us?
14. **deming: PDSA entry.** Plan (hypothesis), Do (implementation), Study (benchmark result),
    Act (keep/revert decision).
15. **Lab notebook entry.** Record: hypothesis, change description, commit SHA, result,
    interpretation, next step.

### Phase 3: Stopping

16. **schon: meta-cognitive check.** After each iteration, assess:
    - Are improvements shrinking? (diminishing returns)
    - Are hypotheses becoming increasingly speculative? (running out of ideas)
    - Has the objective been met? (target reached)
    - Has the iteration budget been exhausted? (max iterations)
17. **If stopping condition met:** proceed to Phase 4.
18. **If not:** return to step 6 with updated knowledge.

### Phase 4: Report

19. **Compile leaderboard.** All attempts ranked by metric value. Include: hypothesis, change,
    result, kept/reverted, commit SHA.
20. **Best-known summary.** The current main branch state with its metric value.
21. **Lessons learned.** What worked, what did not, what surprised us, what to try next.

## Output Format

```
## Autoresearch Loop: [objective]

### Objective: [metric, direction, target]
### Baseline: [value +/- std, commit SHA]

### Leaderboard:
| # | Hypothesis | Change | Result | Delta | Kept? | Commit |
|---|-----------|--------|--------|-------|-------|--------|

### Best known: [value +/- std, commit SHA]

### Stopping reason: [diminishing returns / target reached / budget exhausted]

### Lessons:
- What worked: ...
- What failed: ...
- Surprises: ...
- Next steps (if resuming): ...
```
