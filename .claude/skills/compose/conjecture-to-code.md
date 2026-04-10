---
name: conjecture-to-code
description: >
  Generate candidate patterns rapidly (ramanujan), prove correctness (dijkstra/lamport),
  implement (engineer). The prover is MANDATORY — ramanujan refuses to operate without one.
category: compose
trigger: >
  When a problem space is large and opaque; when rapid hypothesis generation followed
  by rigorous verification is the right workflow; when intuition is faster than analysis
  but correctness is required before shipping.
agents:
  - ramanujan
  - dijkstra
  - lamport
  - engineer
shapes: [conjecture-generator, proof-and-program-together, invariants-not-traces]
input: A problem requiring candidate solutions. The correctness standard.
output: Verified solution: conjectures generated, proof of the selected candidate, implementation.
zetetic_gate:
  logical: "Every conjecture is labeled as conjecture until proven"
  critical: "The prover MUST verify before any conjecture is shipped"
  rational: "Throughput of conjectures is the value; accuracy is the prover's job"
  essential: "No conjecture may be consumed as fact without prover sign-off"
composes: [prove-correct, spec]
aliases: [generate-and-prove, hypothesis-to-code]
hand_off:
  all_conjectures_refuted: "Ramanujan's domain competence may not match — try a different approach"
  conjecture_verified: "/implement — engineer builds it"
---

## Procedure

### Phase 1: Generate (ramanujan)
1. ramanujan: compute 30+ special cases. Play with notation. State conjectures, each labeled as conjecture.
2. Attach evidence (special cases, notational form) to each conjecture.
3. **Gate:** ramanujan REFUSES to operate without a prover assigned for Phase 2.

### Phase 2: Prove (dijkstra or lamport)
4. For sequential/program correctness → dijkstra: develop proof and program together.
5. For concurrent/distributed correctness → lamport: write spec, model-check, prove invariants.
6. **Gate:** only conjectures that survive proof proceed. Refuted conjectures are documented as negative results.

### Phase 3: Implement (engineer)
7. engineer implements the verified solution with the proof as the derivation guide.
8. Tests verify the implementation against the spec/proof.

## Output Format

```
## Conjecture → Code: [problem]

### Conjectures generated: [count]
### Conjectures verified: [count, which ones]
### Conjectures refuted: [count, with reasons — these are findings too]

### Verified solution:
- Conjecture: [statement]
- Proof: [sketch or full]
- Implementation: [files changed]
- Tests: [verification against spec]
```
