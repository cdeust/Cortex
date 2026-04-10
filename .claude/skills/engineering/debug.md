---
name: debug
description: >
  Root-cause debugging using instrumentation, bisection, and carrier isolation.
  No band-aid fixes — trace to the architectural origin.
category: engineering
trigger: >
  When a bug is reported and the cause is unknown; when a test fails intermittently;
  when a symptom is visible but the root cause hasn't been identified.
agents:
  - engineer
  - curie
shapes: [residual-with-a-carrier, instrument-before-hypothesis]
input: >
  A bug report, failing test, or observed symptom with reproduction steps (if available).
output: >
  Root-cause analysis: symptom, instrumentation, bisection log, isolated cause,
  fix with correctness argument, before/after verification.
zetetic_gate:
  logical: "The fix must address the root cause, not the symptom"
  critical: "The cause must be confirmed by instrumentation, not by intuition"
  rational: "Fix the root cause even if a band-aid is faster"
  essential: "One root cause — do not fix adjacent issues in the same change"
composes: [isolate-signal]
aliases: [fix-bug, root-cause]
hand_off:
  concurrency_bug: "/spec — lamport: the spec needs a causality analysis"
  performance_bug: "/performance-investigation — chain fermi→curie→knuth"
  architectural_cause: "/decompose — the architecture is wrong, not the code"
---

## Purpose

Trace a bug to its root cause using the curie method: instrument, measure, name the anomaly, isolate the carrier, confirm with a second method. No band-aid fixes. No "I think it's this." The instrument decides.

## Procedure

1. **Reproduce.** If no reproduction: build one. If intermittent: characterize the conditions under which it appears.
2. **Instrument.** curie Move 1: fix the measurement (logging, tracing, breakpoint, assertion) BEFORE forming a hypothesis.
3. **Survey.** curie Move 3: measure across all plausible components, not just the one you suspect.
4. **Name the anomaly.** curie Move 2: coin a term for the observed deviation. "Checkout-stale-cart-bug" not "the cart thing."
5. **Isolate.** curie Move 4-5: bisect (git bisect, binary search on components, feature flags) until the carrier is isolated. At each step, verify the signal concentrates.
6. **Confirm.** curie Move 6: a second independent method confirms the root cause (e.g., the bisect AND a code review of the identified change agree).
7. **Fix.** engineer implements the fix at the root cause, not at the symptom.
8. **Verify.** Before/after measurement confirms the fix. The original reproduction must now pass.

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Fix addresses root cause, not symptom | Reject symptom-level fixes |
| Critical | Cause confirmed by instrumentation | "I think it's X" is not a finding |
| Critical | Second independent method agrees | Single-method diagnosis is a hypothesis |
| Rational | Root cause fix, even if slower | Band-aids create future bugs |
| Essential | One bug, one fix, one change | Do not fix adjacent issues in the debug PR |

## Output Format

```
## Root Cause Analysis: [bug name]

### Symptom: [what the user sees]
### Reproduction: [steps]
### Instrument: [what measurement was added]
### Survey: [components measured]
### Anomaly: [named deviation]
### Bisection log:
| Step | Hypothesis | Test | Result |
|------|-----------|------|--------|
### Root cause: [identified, with file:line]
### Confirmation: [second independent method]
### Fix: [description + correctness argument]
### Verification: [before/after measurement]
```

## Anti-patterns

- Guessing the cause without instrumenting.
- Band-aid fix at the symptom level.
- "It stopped happening" without understanding why.
- Fixing multiple things in the debug PR (conflates the fix with noise).
