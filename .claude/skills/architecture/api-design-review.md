---
name: api-design-review
description: >
  Review API design: check consistency (Panini), verify contracts (Liskov), assess
  discoverability (Eco), evaluate developer experience (Engelbart), and audit
  abstraction quality (Hopper).
category: architecture
trigger: >
  When an API is being designed or has been designed but not reviewed; when API consumers
  report confusion or misuse; when an API is growing and needs a consistency audit;
  when error handling or versioning strategy is unclear.
agents:
  - liskov
  - hopper
  - engelbart
  - eco
  - panini
shapes: [contract-verification, abstraction-audit, developer-augmentation, model-reader, grammar-consistency]
input: API specification (OpenAPI, proto, GraphQL schema, or code-level interface), plus context on intended consumers.
output: API review report with findings per dimension and prioritized recommendations.
zetetic_gate:
  logical: "Every endpoint must have pre-conditions, post-conditions, and invariants — implicit contracts are bugs"
  critical: "Review must be based on the actual specification, not a summary or description"
  rational: "Recommendations must be prioritized by consumer impact, not aesthetic preference"
  essential: "An API that is consistent but unusable has failed — developer experience is a first-class concern"
composes: [contract, spec]
aliases: [api-review, review-api, api-audit]
hand_off:
  contracts_missing: "/contract — define the missing contracts formally"
  breaking_change_needed: "/adr — document the breaking change decision"
  versioning_unclear: "/spec — specify the versioning strategy"
---

## Procedure

### Phase 1: Consistency Audit (panini)
1. panini: check naming consistency. Are nouns/verbs used consistently across endpoints? Do patterns repeat predictably?
2. panini: check structural consistency. Do similar operations have similar shapes? Are request/response patterns uniform?
3. panini: check convention consistency. HTTP methods, status codes, error formats, pagination — are conventions applied uniformly?
4. **Gate:** inconsistencies must be listed with examples. "It feels inconsistent" is not a finding.

### Phase 2: Contract Verification (liskov)
5. liskov: for each endpoint, identify the pre-conditions (what must be true before calling), post-conditions (what is guaranteed after), and invariants (what is always true).
6. liskov: check substitutability. Can any implementation of this API satisfy these contracts? Are contracts too loose or too tight?
7. **Gate:** implicit contracts must be made explicit. If the behavior is undocumented, it is a bug.

### Phase 3: Abstraction Quality (hopper)
8. hopper: are the abstractions at the right level? Does the API expose implementation details that should be hidden?
9. hopper: are there missing abstractions — operations that consumers need but must compose themselves from primitives?
10. **Gate:** leaky abstractions must be identified with concrete examples of how they leak.

### Phase 4: Discoverability (eco)
11. eco: can a model reader (someone reading only the API docs) understand the API without external context?
12. eco: is the API self-describing? Do names, types, and error messages guide correct usage?
13. **Gate:** if the API requires tribal knowledge to use correctly, it fails the discoverability test.

### Phase 5: Developer Experience (engelbart)
14. engelbart: does the API augment the developer or burden them? Common operations should be easy; uncommon operations should be possible.
15. engelbart: evaluate error handling. Do errors tell the developer what went wrong and how to fix it?
16. Check versioning strategy. Is the evolution path clear for both provider and consumer?

## Output Format

```
## API Design Review: [API name]

### Consistency (panini):
| Finding | Example | Severity |
|---------|---------|----------|

### Contracts (liskov):
| Endpoint | Pre-condition | Post-condition | Invariant | Status |
|----------|--------------|----------------|-----------|--------|

### Abstractions (hopper):
Leaky: [...] | Missing: [...]

### Discoverability (eco):
Self-describing: [yes / partially / no]
Tribal knowledge required: [list]

### Developer experience (engelbart):
Common operations: [easy / moderate / hard]
Error quality: [helpful / vague / misleading]
Versioning: [clear / unclear / absent]

### Prioritized recommendations:
| # | Recommendation | Impact | Effort |
|---|---------------|--------|--------|
```
