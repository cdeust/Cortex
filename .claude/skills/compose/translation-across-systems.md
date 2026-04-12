---
name: translation-across-systems
description: >
  Import a solution from one domain to another: find the isomorphism (Von Neumann),
  check topological equivalence (Poincare), identify where the analogy breaks (Midgley),
  and bootstrap across representations (Champollion).
category: compose
trigger: >
  When a solution from another field seems applicable but hasn't been rigorously mapped;
  when "it works like X in domain Y" is asserted without checking the structural
  correspondence; when an analogy is doing load-bearing work without verification.
agents:
  - vonneumann
  - poincare
  - midgley
  - champollion
shapes: [isomorphism-map, topological-equivalence, analogy-break, bilingual-bootstrap]
input: Source solution (from domain A), target problem (in domain B), and the claimed analogy.
output: Structural correspondence map, verified adaptation, and documented break points.
zetetic_gate:
  logical: "The structural correspondence must be explicit and testable, not metaphorical"
  critical: "Where the analogy breaks must be identified before the adaptation is trusted"
  rational: "The adapted technique must be verified in the target domain, not assumed to transfer"
  essential: "Import the structure, not the surface — reject cargo-cult analogies"
composes: [verify-claim, cargo-cult-check]
aliases: [cross-domain, analogy-transfer, domain-translation, import-technique]
hand_off:
  analogy_breaks_badly: "(stop) — the structural correspondence does not hold"
  adaptation_needs_testing: "/experiment — test the adapted technique in the target domain"
  mechanism_unclear: "/rederive — rederive the technique from first principles in the target domain"
---

## Procedure

### Phase 1: Find the Isomorphism (vonneumann)
1. vonneumann: state the source solution formally. What are its objects, operations, and invariants?
2. vonneumann: state the target problem formally. What are its objects, operations, and constraints?
3. vonneumann: map the correspondence. For each element in the source, what is the candidate element in the target?
4. **Gate:** the mapping must be explicit and structural, not metaphorical ("it's kind of like...").

### Phase 2: Check Topological Equivalence (poincare)
5. poincare: is this the same problem in disguise? Check if the problems are topologically equivalent — same structure under continuous deformation.
6. poincare: what properties are preserved under the mapping? What properties are not?
7. **Gate:** if key properties are not preserved, the transfer requires adaptation, not copy.

### Phase 3: Identify Where the Analogy Breaks (midgley)
8. midgley: where does the analogy break? What assumptions in domain A do not hold in domain B?
9. midgley: what is the cost of the breakage? Is it a minor edge case or a fundamental mismatch?
10. **Gate:** if the analogy breaks at a load-bearing point, the transfer fails. Stop or redesign.

### Phase 4: Adapt and Verify (champollion)
11. champollion: bilingual bootstrapping — use the known correspondence to translate, then verify the translation independently in the target domain.
12. Produce the adapted technique with explicit documentation of what was preserved, what was changed, and why.

## Output Format

```
## Translation: [source domain] → [target domain]

### Source solution: [formal description]
### Target problem: [formal description]

### Structural correspondence (vonneumann):
| Source element | Target element | Correspondence type |
|--------------|---------------|-------------------|

### Topological equivalence (poincare):
Equivalent: [yes / partial / no]
Preserved properties: [...]
Lost properties: [...]

### Analogy breaks (midgley):
| Break point | Severity | Workaround |
|------------|----------|-----------|

### Adapted technique (champollion):
[description of the adapted technique]
Verified in target domain: [yes / pending]
```
