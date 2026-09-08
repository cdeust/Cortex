# Cortex — Persistent Memory MCP Server

Persistent memory and cognitive profiling MCP server for Claude Code. Python 3.10+,
FastMCP, Pydantic, numpy; SQLite by default, PostgreSQL+pgvector opt-in (`PRIVACY.md`).

This file is deliberately short: the host harness (hooks, skills, agents) loads what it
needs on demand. Everything that used to be here is in `docs/agent-guidance.md`
(architecture pointers, releasing, code style and the craftsmanship gate, what not to do,
the zetetic implementation standard). Read it before any non-trivial change.

## Build & Test

- Install (dev): `uv sync --no-default-groups --extra dev` (add `--extra sqlite` for the
  SQLite backend). Resolve from `uv.lock`, never from the `pyproject.toml` ranges (issue #253).
- Preflight: `python -m mcp_server.doctor`
- Tests: `pytest` · one layer: `pytest tests_py/core/`
- Lint before every commit: `ruff check && ruff format --check` (CI enforces both).
- Type gate: CONTRIBUTING.md § *Reproducing the pyright gate locally*.
- Craftsmanship gate: `python scripts/check_craftsmanship.py` (300 lines per file, 40 per
  method, layer whitelist, `# source:` on every constant).
- Release-gate benchmarks: `benchmarks/reproduce.sh`, never against the live database.

## Non-negotiables

- Layers: `server → handlers → core ← shared`, `infrastructure → shared`; handlers are the
  only composition roots.
- Every git worktree lives at `.claude/worktrees/<name>/`, never outside the repo.
- No source, no implementation; benchmark before commit; no silent fallbacks or
  compatibility shims.
