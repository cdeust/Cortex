---
name: implement
description: >
  Implement a feature with layer-aware design: identify the right architectural layer,
  design interfaces, write code, wire dependencies, verify.
category: engineering
trigger: >
  When a feature needs to be built; when a task requires new code in the right place
  with the right dependency direction.
agents:
  - engineer
  - architect
  - test-engineer
shapes: []
input: A feature description or task specification.
output: Working implementation with tests, respecting layer boundaries and SOLID principles.
zetetic_gate:
  logical: "Dependencies point inward; core never imports infrastructure"
  critical: "Tests cover the new behavior; tests fail without the implementation"
  rational: "Simplest implementation that satisfies the spec — no speculative abstractions"
  essential: "Only what was asked — no extra features, no unsolicited refactoring"
composes: []
aliases: [build, code]
hand_off:
  needs_design: "/decompose — architect decomposes first if scope is large"
  needs_spec: "/spec — lamport writes spec first if concurrent/distributed"
  needs_review: "/review — code-reviewer reviews the implementation"
---

## Purpose

Implement a feature correctly in the right architectural layer. The architect identifies where the code belongs; the engineer writes it; the test-engineer verifies it. Dependencies point inward. No speculative abstractions. No extra features.

## Procedure

1. **architect identifies the layer.** Where does this feature live? Core (pure logic), infrastructure (I/O), handlers (wiring)?
2. **architect designs interfaces.** If the feature crosses layers, define the interface in core; implement in infrastructure; wire in handlers.
3. **engineer implements.** Writes the code in the identified layer with the designed interfaces. SOLID throughout: single responsibility per module, dependency inversion, no god classes.
4. **test-engineer writes tests.** Unit tests for core logic (no mocks needed if core is pure). Integration tests for the wiring. Tests must fail without the implementation (red-green).
5. **Verify.** All tests pass. Layer boundaries respected. No new anti-patterns introduced.

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | Dependencies point inward | Restructure before writing code |
| Critical | Tests fail without implementation, pass with it | Rewrite tests if they pass without the code |
| Rational | Simplest implementation | Remove speculative abstractions |
| Essential | Only what was asked | Cut unsolicited features and refactoring |

## Output Format

```
## Implementation: [feature name]

### Layer: [core / infrastructure / handlers]
### Interfaces defined: [list with file:line]
### Files changed: [list]
### Tests added: [list with coverage of new behavior]
### Dependency direction: [verified inward]
```

## Anti-patterns

- Writing code before identifying the layer.
- Core importing infrastructure.
- Tests that pass without the implementation (tautological tests).
- Speculative abstractions for hypothetical future requirements.
- Unsolicited refactoring bundled with the feature.
