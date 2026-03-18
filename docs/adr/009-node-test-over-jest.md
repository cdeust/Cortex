# ADR-009: node:test Over Jest

## Status
Accepted

## Context
Need a test framework for unit and integration tests. Must align with the zero-dependency principle (ADR-001) while providing sufficient testing capabilities.

## Decision
Use Node.js built-in test runner (`node:test` module + `node:assert`) available since Node.js 18. Run tests with `node --test`.

## Consequences
- **Gain**: Zero additional dependencies. Ships with Node.js — no install, no version management. Fast startup (no transpilation or loader overhead). Consistent with ADR-001 zero-dependency principle.
- **Lose**: Less feature-rich than Jest: no built-in snapshot testing, limited mocking API, no watch mode in earlier versions, smaller ecosystem of plugins and matchers.
- **Neutral**: `describe`/`it`/`assert` API is familiar. Coverage reporting available via `--experimental-test-coverage` flag. Sufficient for a plugin of this size.

## References
- Node.js documentation: Test runner — https://nodejs.org/api/test.html
- Node.js documentation: Assert — https://nodejs.org/api/assert.html
