---
created: 2026-09-16T17:09:11Z
kind: adr
number: 1075
status: accepted
tags: [procedural-memory, sqlite, parity, issue-596]
title: Procedural skills are stored on both backends
---
# ADR-1075: Procedural skills are stored on both backends

## Status

accepted

## Context

`procedural_skills` existed only on PostgreSQL: `pg_schema.py` declares the table (ADR-0558) and `pg_store_procedural.PgProceduralMixin` implements `upsert_procedural_skill` and `get_procedural_skills`, with nothing of the kind in the SQLite schema or store. Checked at runtime against a store built through the real composition root, `SqliteMemoryStore` had neither method (issue #596).

`handlers/procedural_skill_writer.maybe_mine_skills` calls `store.upsert_procedural_skill` for every mined skill, inside a `try` whose `except Exception` returns `{"status": "error"}`. On SQLite the mining therefore ran, produced its skills, and lost each one to an `AttributeError` nobody reads, so `recall_skills` could only ever return an empty list.

SQLite is the default backend for plugin installs, `.mcpb` and Cowork (PRIVACY.md lines 26-38), and `README.md` advertises all 54 tools as working on both backends with an identical retrieval contract. A PostgreSQL-only skills table makes that claim false for `recall_skills`.

This was invisible while the capture path produced no input at all: every session entry carried `toolsUsed: []` until ADR-1072.

## Decision

SQLite gets the table and the two operations, in `sqlite_schema_procedural.py` and `sqlite_store_procedural.SqliteProceduralMixin`, mirroring the PostgreSQL columns with SQLite's spellings: `INTEGER PRIMARY KEY AUTOINCREMENT` for the serial, `INTEGER` for the boolean, ISO-8601 text for the timestamps, as the rest of that schema does. `get_all_ddl` includes them, so an existing database picks the table up on its next open through `CREATE TABLE IF NOT EXISTS`, with no migration entry: the table is new, not a column added to an old one.

`upsert_procedural_skill` returns the row id and `get_procedural_skills` returns `is_habitual` as a bool, so a handler reads the same shapes on either backend.

## Consequences

Easier: a session end persists what it mined wherever Cortex runs, and `recall_skills` can return something on the default install.

`tests_py/infrastructure/test_sqlite_procedural.py` covers the two operations present, a round trip including the boolean and the timestamp, the upsert updating in place rather than duplicating, the proficiency floor, and the end-to-end writer path persisting what `mine_skills` produced. All five fail on the previous code.

Harder: two implementations of the same table to keep in step. The columns are few and the contract is pinned by tests on both sides.

Unchanged: mining itself, and the reward it reads. Proficiency stays at 0.5 for every skill until a session records an outcome, which is the next decision, not this one (issue #597).
