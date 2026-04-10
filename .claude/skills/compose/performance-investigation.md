---
name: performance-investigation
description: >
  End-to-end performance investigation: bracket the expected (fermi), measure the actual
  and isolate the residual (curie), profile the hot path and fix the 3% (knuth).
category: compose
trigger: >
  When a system is "slow" but nobody has measured where the time goes; when latency exceeds
  the sum of profiled components; when optimization is proceeding without profiling data.
agents:
  - fermi
  - curie
  - knuth
  - engineer
shapes: [order-of-magnitude-first, residual-with-a-carrier, profile-before-optimizing]
input: A slow system or component with whatever metrics are currently available.
output: Performance report: expected bracket, measured actuals, profiled hot path, fix with before/after.
zetetic_gate:
  logical: "Expected bracket must be dimensionally consistent with measurements"
  critical: "Measured values from instrumentation, not intuition"
  rational: "Fix only the profiled 3%; leave the 97% alone"
  essential: "Stop when measured value falls within the expected bracket"
composes: [estimate, isolate-signal, optimize]
aliases: [perf-investigate, why-slow]
hand_off:
  architecture_wrong: "/decompose — the architecture is the bottleneck, not the code"
  algorithm_wrong: "/prove-correct — need algorithmic redesign, not tuning"
---

## Procedure

### Phase 1: Bracket (fermi)
1. `/estimate` the performance quantity. Decompose into known components. Produce a two-sided bracket.
2. **Gate:** if bracket LOW > requirement, the architecture is wrong → hand off to `/decompose`.

### Phase 2: Measure and isolate (curie)
3. Instrument the system. Measure actual under controlled conditions.
4. If actual within bracket → investigation complete (system performs as expected).
5. If actual exceeds bracket → the excess is a residual. curie isolates by bisection/ablation.
6. **Gate:** two independent methods confirm the residual carrier.

### Phase 3: Profile and fix (knuth + engineer)
7. knuth profiles the identified component. Identifies the 3% hot path. Analyzes complexity.
8. engineer implements the fix. Only the hot path.
9. curie re-measures. Before/after with statistical comparison.

## Output Format

```
## Performance Investigation: [system/component]

### Phase 1 — Expected: [bracket from fermi]
### Phase 2 — Measured: [actual from curie]
### Residual: [excess, carrier identified by curie]
### Phase 3 — Hot path: [from knuth profile, % of runtime]
### Fix: [what changed]
### Before: [value ± CI] → After: [value ± CI]
### Improvement: [X%]
```
