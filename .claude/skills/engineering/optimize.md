---
name: optimize
description: >
  Performance optimization with the Knuth discipline: profile first, identify the 3% hot path,
  optimize only that, leave the 97% alone. Before/after measurement required.
category: engineering
trigger: >
  When a system is slow and someone wants to "optimize the code"; when optimization is
  proceeding without profiling data; when "premature optimization" is being invoked to
  block necessary optimization of a known bottleneck.
agents:
  - knuth
  - engineer
  - curie
shapes: [profile-before-optimizing, premature-optimization-in-context]
input: A slow system or component with (ideally) a performance target.
output: >
  Optimization report: profile results, hot path identified, fix applied, before/after
  measurement with statistical comparison.
zetetic_gate:
  logical: "Algorithm complexity class must be known before optimizing constants"
  critical: "Profile data required — no optimization by intuition"
  rational: "Fix only the 3%; leave the 97% readable"
  essential: "Stop when measured performance meets the target"
composes: []
aliases: [perf, speed-up]
hand_off:
  wrong_algorithm: "/prove-correct — dijkstra: the algorithm needs redesign, not tuning"
  architecture_bottleneck: "/decompose — the architecture is the constraint"
  need_estimate_first: "/estimate — fermi brackets before measuring"
---

## Purpose

Knuth's full discipline: "We should forget about small efficiencies, say about 97% of the time: premature optimization is the root of all evil. Yet we should not pass up our opportunities in that critical 3%." Profile to find the 3%. Optimize that. Leave the rest alone. Measure before and after.

## Procedure

1. **knuth: complexity analysis.** What is the algorithm's Big-O? For the current data size, is the complexity class feasible? If not, the algorithm is wrong — hand off to /prove-correct.
2. **curie: measure baseline.** Instrument the system. Measure the current performance under controlled conditions. This is the "before."
3. **knuth: profile.** Run the profiler (CPU, memory, I/O as appropriate). Identify the hot path — the 3% consuming most of the time.
4. **knuth: propose fix.** For the hot path only. With complexity analysis of the proposed change.
5. **engineer: implement.** Apply the fix to the hot path only. Do not touch the 97%.
6. **curie: measure after.** Same conditions as baseline. Statistical comparison (not a single run).
7. **Report.** Profile, hot path, fix, before/after with confidence interval.

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Complexity class known | Analyze before optimizing |
| Critical | Profile data exists | No optimization without profiling |
| Rational | Only the 3% is touched | Reject changes to non-hot-path code |
| Essential | Stop at the target | No gold-plating once performance target is met |

## Output Format

```
## Optimization Report

### Complexity: [O(?) for current data size — feasible?]
### Profile: [hot path identified with % of runtime]
### Baseline: [measured value ± CI]
### Fix: [what was changed, complexity of new approach]
### After: [measured value ± CI]
### Improvement: [X% ± CI]
### The 97%: [unchanged, confirmed]
```

## Anti-patterns

- Optimizing without profiling.
- Quoting "premature optimization" to block optimization of a profiled bottleneck.
- Optimizing the 97% because it's easier to understand.
- Single-run before/after without statistical comparison.
- Changing the algorithm AND the constants in the same PR (can't attribute improvement).
