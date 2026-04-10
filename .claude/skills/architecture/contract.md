---
name: contract
description: >
  Define behavioral contracts at composition boundaries: preconditions, postconditions,
  invariants, history constraints. Liskov substitutability as the correctness criterion.
category: architecture
trigger: >
  When an interface has methods but no behavioral specification; when a swap-test fails
  (replacing an implementation breaks callers); when callers depend on internal representation.
agents:
  - liskov
  - architect
shapes: [substitutability-as-contract, behavioral-subtyping, contract-is-interface, composition-correctness]
input: The interface or boundary to specify.
output: Behavioral contract with pre/post/invariant/history constraint for each operation.
zetetic_gate:
  logical: "Pre/post/invariant must be internally consistent"
  critical: "Swap-test every implementation against the contract"
  rational: "Specification depth proportional to boundary criticality"
  essential: "The contract IS the interface — the minimum that guarantees composability"
composes: []
aliases: [define-contract, behavioral-contract, interface-spec]
hand_off:
  distributed_boundary: "/spec — lamport: the boundary needs a full protocol spec"
  implementation_needed: "/implement — engineer builds an implementation that satisfies the contract"
---

## Procedure

1. **liskov: list operations.** What operations does this interface expose?
2. **liskov: for each operation.** Precondition (what the caller must satisfy), postcondition (what the implementation promises), invariant (what is always true).
3. **liskov: history constraint.** What sequences of operations are valid? What state trajectories must be preserved?
4. **Swap-test.** For each known implementation: does it satisfy the contract? Where does it violate?
5. **Pre/post direction check.** Preconditions may weaken (accept more), postconditions may strengthen (promise more). Violating either direction is a contract breach.
6. **Abstraction check.** Are callers depending on internal representation? If yes, hide it.

## Output Format

```
## Contract: [interface name]
### Operations:
| Operation | Precondition | Postcondition | Invariant |
|---|---|---|---|
### History constraint: [valid operation sequences]
### Swap-test results:
| Implementation | Substitutable? | Violations |
|---|---|---|
### Pre/post direction:
| Implementation | Pre weaker? | Post stronger? | OK? |
|---|---|---|---|
### Abstraction: [callers depending on internals?]
```
