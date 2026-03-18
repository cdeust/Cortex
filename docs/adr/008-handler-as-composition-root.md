# ADR-008: Handlers as Composition Roots

## Status
Accepted

## Context
Need to wire infrastructure I/O (file reads, cache lookups) to pure core logic (profiling, clustering, classification) without polluting core modules with side effects.

## Decision
Each handler file serves as a composition root: it reads from infrastructure, passes data to core functions, and formats the response. Core modules are pure — data in, data out. Infrastructure modules handle all I/O.

```
Handler: read files → call core(data) → format response
Core:    pure function(data) → result
Infra:   readFile() → data
```

## Consequences
- **Gain**: Core modules are fully testable without mocks or stubs. I/O is isolated to infrastructure and wired only in handlers. Clear separation of "what" (core) from "how" (infrastructure).
- **Lose**: Handlers can become verbose when wiring many dependencies. Some duplication of data-fetching patterns across handlers.
- **Neutral**: Follows naturally from the clean architecture layer rules (ADR-002). Handlers are thin — typically 30-60 lines.

## References
- Seemann, M. "Composition Root" pattern — blog.ploeh.dk (2011)
- Martin, R. "Clean Architecture" — Chapter 22: The Clean Architecture (2017)
