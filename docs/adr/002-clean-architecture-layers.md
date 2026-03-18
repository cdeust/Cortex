# ADR-002: Clean Architecture Concentric Layers

## Status
Accepted

## Context
The original codebase was a monolithic 580-line `index.js` with a grab-bag `utils.js`. Business logic, I/O, and transport were interleaved, making testing and modification difficult.

## Decision
Adopt six concentric layers with strict dependency rules — inner layers never import outer:

1. **shared** — Constants, configuration, pure utilities
2. **core** — Domain logic (pure functions, no I/O)
3. **infrastructure** — File system, caching, external reads
4. **handlers** — Composition roots wiring infra → core → response
5. **server** — JSON-RPC dispatch and tool registry
6. **transport** — stdio communication layer

## Consequences
- **Gain**: Clear testability boundaries. Core logic is pure and testable without mocks. Dependency inversion for all I/O. Each layer has a single reason to change.
- **Lose**: More files and directories. Developers must understand which layer a module belongs to. Slight indirection overhead.
- **Neutral**: Import paths are longer but self-documenting.

## References
- Martin, R. "Clean Architecture: A Craftsman's Guide to Software Structure and Design" (2017)
- Martin, R. "The Clean Architecture" blog post (2012)
