---
created: 2026-10-20T16:00:00Z
kind: adr
number: 1110
status: accepted
tags: [backend, sqlite, postgresql, launcher, hooks, install, privacy]
title: One backend resolution for the launcher, the hooks and the server
---
# ADR-1110: One backend resolution for the launcher, the hooks and the server

## Status

accepted. Extends ADR-1104 (first-launch decision) from the Claude Code launcher to every entry point. Amends ADR-0505 (the server no longer leaves an unconfigured HOME to the engine's `auto`) and ADR-0535 for entry points only: the hook entry no longer runs the store's `auto` selection; `memory_store`'s own `auto` branch is unchanged for library callers.

## Context

Issues #703 and #704. Measured on main df3a447, 2026-10-20, Linux, a fresh HOME with no marker, no `DATABASE_URL`, no `PG*` variable, and a listener on `127.0.0.1:5432` that counts connections:

| Entry point | Connections to :5432 | Marker | Result |
|---|---|---|---|
| `scripts/launcher.py mcp_server.hooks.session_start` (Claude Code plugin) | 0 | `sqlite` | ADR-1104 holds |
| `python -m mcp_server.hooks.entry session_start` (`hypermnesia-mcp-hook`, Codex) | 1 | none | dials a PostgreSQL nobody configured |
| `python -m mcp_server.hooks.entry auto_recall` | 1 | none | idem |
| `python -m mcp_server` (`hypermnesia-mcp`) + `remember` | 1 | none | `remember` fails: "Cortex requires PostgreSQL in CLI mode" |

Cause: three resolutions. `scripts/launcher_backend.py` called `apply_backend_resolution(..., default="sqlite")` after the ADR-1104 first decision; `mcp_server/hooks/entry.py` called it without a default, then set `DATABASE_URL=postgresql://localhost:5432/cortex` or ran the store's `auto` selection; `mcp_server/__main__.py` called it without a default, so the engine's `auto` dialed `memory_config.DATABASE_URL`. The hooks also defaulted `DATABASE_URL` to `127.0.0.1:5432` / `localhost:5432` (`session_start_common.py`, `auto_recall.py`).

## Decision

1. `mcp_server/infrastructure/backend_resolution.py` holds the ADR-1104 first-launch decision (moved verbatim from `scripts/launcher_backend.py`) and `settle_backend(environ, marker_path=None)`, the only resolution: explicit environment, then marker, then a first decision recorded as the marker, then `CORTEX_MEMORY_STORE_BACKEND` is `sqlite` or `postgresql` — never `auto`. `DATABASE_URL` is set only for PostgreSQL (the namespaced URL, else the ADR-1104 legacy local URL when PostgreSQL was chosen).
2. The launcher (`scripts/launcher_backend.apply`), the hook entry (`hooks/entry.prepare_environment`) and the server (`mcp_server/__main__.py`) call `settle_backend`. An unreadable marker stops the process with "Cortex not ready" (no guessed backend).
3. `hooks/entry.resolve_auto_backend` is removed: an entry point can no longer reach `auto`.
4. The hook modules have no default URL; their PostgreSQL helpers return `None` when `DATABASE_URL` is unset.

## Consequences

- Acceptance test `tests_py/integration/test_unconfigured_home_never_dials_postgres.py` runs the three wheel entry points in subprocesses against a real listener on `127.0.0.1:5432`: 3 failed on main df3a447, 3 pass with this change. It skips when the port is already taken, because a real server there is what must never be reached.
- A Codex HOME with no configuration now gets SQLite and a marker, like a Claude Code HOME; before, it probed `127.0.0.1:5432` on every hook and used PostgreSQL whenever one answered.
- Not changed here: `memory_config.DATABASE_URL`'s default (used by library callers and tests through `auto`). Removing it is the remaining part of #704's "no default URL in code".
