---
created: 2026-09-22T23:12:06Z
kind: adr
number: 1088
status: accepted
tags: [adr]
title: Persist install-plugin.sh's backend marker before scripts/setup.py can fail
---
# ADR-1088: Persist install-plugin.sh's backend marker before scripts/setup.py can fail

## Status

accepted

## Context

`scripts/install-plugin.sh` decides the storage backend (SQLite default, PostgreSQL opt-in or auto-detected) in Phase 0, then runs `scripts/setup.py` (or `scripts/setup.sh`) to provision it, then persists the decision to `~/.claude/methodology/backend.json`. `scripts/launcher.py` reads that marker on every future launch (via `backend_marker.apply_backend_resolution`) to set `CORTEX_MEMORY_STORE_BACKEND`.

The marker write previously sat *after* the setup step, guarded by `|| fail "scripts/setup.py failed. ..."`. `fail()` calls `exit 1`, so any setup failure — a Windows torch/torchaudio conflict (issue #621/#633), a network blip during dependency install, anything — discarded a backend decision that had already been made correctly in Phase 0.

Issue #633 traced the consequence: `mcp_server/infrastructure/memory_config.py::_detect_runtime()` defaults to `"cli"` runtime when neither `CORTEX_RUNTIME` nor `CLAUDE_ENVIRONMENT=cowork` is set — which is exactly the Claude Code plugin's own `plugin.json` (`"CORTEX_RUNTIME": ""`). `mcp_server/infrastructure/memory_store.py::_construct_store()` forces `backend = "postgresql"` whenever `runtime == "cli" and backend == "auto"`. So a missing marker does not fall back to SQLite — it silently converts a correctly-chosen SQLite install into a hard PostgreSQL requirement on every subsequent launch, with no PostgreSQL ever provisioned to satisfy it (`check_setup` then reports `database_not_connected`).

## Decision

Write the backend marker immediately after the backend is decided (`say "Backend: $BACKEND"`), before `scripts/setup.py`/`scripts/setup.sh` runs and before either can `fail` and exit the script. The marker records a *decision*, not a completed install — it does not depend on setup succeeding, and setup's own success/failure is still reported and still exits non-zero on failure. No third marker state (e.g. `"setup": "incomplete"`) is introduced: nothing downstream reads such a field, and a marker that says "sqlite" but whose setup failed is still strictly better than no marker, since the alternative (auto → forced PostgreSQL under `RUNTIME=cli`) is actively wrong for a user who never asked for PostgreSQL.

## Consequences

A `scripts/setup.py` failure (Windows dependency conflict, network blip, anything) after this point still fails the install and reports the real cause — but it no longer also corrupts the *next* launch's backend resolution. A user who re-runs the installer or fixes the underlying failure keeps the SQLite (or PostgreSQL) marker their Phase 0 choice already established.

This does not change behavior for the reporter's own repro: their machine had an existing PostgreSQL install (marker or reachable `psql`), so Phase 0 chose `postgresql` — that install still requires PostgreSQL to be running, matching install-plugin.sh's documented "never silently downgrade a Postgres install to SQLite" rule. It is the SQLite-default, no-PostgreSQL-at-all case that this fix protects, which is the majority zero-config path.

A PostgreSQL → SQLite migration path remains out of scope — a pre-existing, separate gap the reporter also noted, worth its own issue.
