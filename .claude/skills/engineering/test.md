---
name: test
description: >
  Design a test suite with appropriate coverage. Acknowledge what testing CAN and CANNOT prove
  (Dijkstra: testing shows presence, not absence, of bugs).
category: engineering
trigger: >
  When new code needs tests; when test coverage is insufficient; when someone asks
  "what should we test?" for a module.
agents:
  - test-engineer
  - dijkstra
shapes: [tests-insufficient]
input: Code or module to test. Context on criticality.
output: Test plan with unit/integration/e2e breakdown, what is covered, and what testing CANNOT cover.
zetetic_gate:
  logical: "Tests must be independent and deterministic"
  critical: "Tests must fail without the implementation (red-green)"
  rational: "Coverage proportional to criticality"
  essential: "Acknowledge what tests cannot prove; recommend stronger methods for those"
composes: []
aliases: [write-tests, test-plan]
hand_off:
  concurrent_code: "/spec — lamport: model-check, don't just test"
  critical_path: "/prove-correct — dijkstra: proof + tests, not tests alone"
---

## Procedure

1. **test-engineer identifies what to test.** Happy paths, error paths, edge cases, boundary conditions.
2. **dijkstra identifies what testing cannot cover.** Concurrency interleavings, numerical edge cases, security guarantees. These need stronger methods.
3. **Test plan.** Unit (core logic, pure functions), integration (wiring, I/O), e2e (user-facing flows). Coverage target proportional to criticality.
4. **Write tests.** Each test: clear name, arrange-act-assert, one assertion per behavior, deterministic.
5. **Verify red-green.** Each test fails without the implementation, passes with it.

## Output Format

```
## Test Plan: [module]

### Criticality: [high/medium/low]
### What testing covers:
| Test type | What it verifies | Count |
|-----------|-----------------|-------|

### What testing CANNOT cover:
| Gap | Why testing is insufficient | Recommended method |
|-----|---------------------------|-------------------|

### Tests written: [list with names]
```
