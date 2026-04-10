---
name: decompose
description: >
  Module decomposition: identify forces, propose boundaries, evaluate trade-offs,
  verify dependency direction.
category: architecture
trigger: >
  When a codebase has grown into a monolith; when adding a feature touches too many files;
  when team ownership boundaries don't match code boundaries.
agents:
  - architect
  - engineer
  - kekule
shapes: [separation-of-concerns, structural-hypothesis-from-constraints, valence-counting]
input: The area to decompose. The forcing reason (scaling, team ownership, complexity).
output: Decomposition proposal with boundaries, interfaces, dependency graph, and migration path.
zetetic_gate:
  logical: "Dependencies point inward; no circular dependencies"
  critical: "Every boundary has a forcing reason — not 'it feels like a good split'"
  rational: "Boundaries match team ownership and deployment units"
  essential: "Minimum number of modules; splits have forcing reasons"
composes: [contract]
aliases: [split, modularize]
hand_off:
  needs_contracts: "/contract — liskov defines behavioral contracts at new boundaries"
  needs_implementation: "/implement — engineer builds the new structure"
  needs_migration: "/refactor — incremental migration plan"
---

## Procedure

1. **kekule: count the connections.** How many imports/exports does each module have (its "valence")? Which modules are over-connected?
2. **architect: identify forces.** Why split? (Team ownership, deployment independence, complexity reduction, compile time.) Every split must have a forcing reason.
3. **architect: propose boundaries.** Where do the natural seams fall? (High cohesion within, low coupling between.)
4. **Dependency graph.** Draw the proposed dependency graph. Verify all arrows point inward. No cycles.
5. **Interface design.** At each new boundary, define the interface (what crosses the boundary and how).
6. **Migration path.** Incremental steps from current to proposed, each independently deployable.

## Output Format

```
## Decomposition: [area]
### Forcing reasons: [why split]
### Proposed modules:
| Module | Responsibility | Valence (imports/exports) |
|--------|---------------|-------------------------|
### Dependency graph: [arrows, all pointing inward]
### New interfaces: [at each boundary]
### Migration steps: [incremental, each deployable]
```
