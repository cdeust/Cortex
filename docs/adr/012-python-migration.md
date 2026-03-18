# ADR-012: Python Migration from Node.js

## Status

Accepted

## Context

The Methodology Agent was originally implemented as a zero-dependency Node.js application (8,363 lines, 44 files). While the zero-dependency constraint kept the system self-contained, it required hand-rolling linear algebra, sparse vector operations, and type definitions that have mature library solutions in Python.

Additionally, the broader MCP ecosystem has converged on Python and Go as the primary implementation languages. The user builds all MCPs in Python or Go, making the Node.js implementation an outlier in the stack.

Future planned features — numpy-based similarity computations, sentence-transformers for semantic matching, sqlite-vec for vector storage — all have first-class Python support.

## Decision

Incrementally port the entire codebase from JavaScript to Python, following a 12-phase bottom-up migration strategy that preserves the Clean Architecture layer structure.

### Migration Strategy

Port leaf dependencies first, working upward through the layer hierarchy:

1. **Phases 1-3:** Shared utilities (text, hash, yaml, similarity, categorizer, project_ids, linear_algebra, sparse)
2. **Phase 4:** Error hierarchy + Pydantic types (replacing JSDoc)
3. **Phase 5:** Validation schemas (Pydantic models)
4. **Phases 6-8:** Core domain logic (12 modules)
5. **Phase 9:** Infrastructure (filesystem I/O, MCP client, scanner)
6. **Phase 10:** Handlers (10 tool composition roots)
7. **Phase 11:** Server + transport + entry point
8. **Phase 12:** Hooks + final verification

### Key Technology Choices

| Concern | JS (before) | Python (after) |
|---|---|---|
| Linear algebra | Hand-rolled 200+ lines | numpy (~80 lines) |
| Type definitions | JSDoc annotations | Pydantic models (runtime validation) |
| Sparse vectors | Custom Map-based | dict-based (native) |
| Test framework | node:test | pytest + pytest-cov |
| Build system | None (zero-dep) | hatchling (pyproject.toml) |
| Entry point | `node mcp-server/index.js` | `python -m mcp_server` |
| Async I/O | child_process.spawn | asyncio.create_subprocess_exec |
| Path handling | path.join() | pathlib.Path |

## Consequences

### Positive

- **23% line reduction** (8,363 -> ~6,400 lines) from numpy vectorization and Pydantic compression
- **Runtime type validation** via Pydantic models (vs build-time-only JSDoc)
- **Ecosystem alignment** with Python-based MCP servers
- **Future-proofing** for numpy, sentence-transformers, sqlite-vec features
- **Mature testing** via pytest fixtures (tmp_path, monkeypatch, parametrize)

### Negative

- **New dependency** on numpy and pydantic (breaking the zero-dependency tradition from ADR-001)
- **Async model change** from Node.js event loop to Python asyncio (different debugging model)
- **Transition period** maintaining both JS and Python codebases until verification complete

### Neutral

- Clean Architecture layer structure preserved identically
- All 10 core algorithms ported with identical behavior (verified by test parity)
- Data format (profiles.json) remains compatible between JS and Python implementations

## Verification

- All 500+ Python tests passing
- Coverage targets maintained (shared 95%+, core 90%+, infrastructure 85%+, handlers 85%+)
- Swap `.mcp.json` to `python -m mcp_server` and verify all 9 tools work in Claude Code
