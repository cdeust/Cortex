# ADR-001: Zero External Dependencies

## Status
Accepted

## Context
MCP plugins run inside Claude Code's process. Any external dependency introduces supply chain risk, version conflicts with the host process, and increased startup time. The plugin must remain lightweight and trustworthy.

## Decision
Use zero external npm dependencies. Rely exclusively on Node.js built-in modules: `fs`, `path`, `os`, `http`, `crypto`, and `node:test`. All functionality is implemented with pure Node.js.

## Consequences
- **Gain**: No supply chain attack surface. No `node_modules` to manage. No version conflicts with Claude Code's runtime. Instant installs.
- **Lose**: Slightly more code for things a library might handle (e.g., JSON schema validation, HTTP routing). Must implement utilities that libraries provide for free.
- **Neutral**: Forces deliberate API design since every utility is hand-written.

## References
- Node.js built-in modules documentation: https://nodejs.org/api/
- "The Cost of Small Modules" — Nolan Lawson (2016)
