---
kind: adr
number: 0603
title: Preserve sqlite_schema_wiki design decisions
status: accepted
---

# ADR-0603: sqlite_schema_wiki design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/sqlite_schema_wiki.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
SQLite has no schema namespaces, so `wiki.<table>` is flattened to
`wiki_<table>`; sqlite_sql_translate._translate_sql rewrites the SQL on the
way in (imported by sqlite_compat.py, issue #260), which is what lets the
52 modules that query these tables run unmodified on both backends.
````

### module, original line 1

````text
Type mapping applied here (issue #206):
````

### comment, original line 105

````text
# status/lifecycle_state vocabularies mirror pg_schema.py's wiki.pages
# CHECK constraints verbatim — see that file for the provenance of each
# value (core/wiki_templates.py STATUS_VALUES, auto_curator 'living', etc.).
````

### comment, original line 213

````text
# Index parity with pg_schema.py minus the two PostgreSQL-only families:
# HNSW (pgvector ANN) and GIN (tags containment). Partial indexes are kept —
# SQLite supports them — with `NOT is_stale` rewritten to `is_stale = 0`
# because is_stale is INTEGER here, not BOOLEAN.
````

### comment, original line 246

````text
# Order matters: wiki_concepts and wiki_pages precede the tables whose
# foreign keys reference them (PRAGMA foreign_keys=ON is set on connect).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### SQL literal, source line 1

````sql
-----------------------------|-------------------------------------|
````

### SQLite schema operational mapping and original decision rationale

````text
SQLite mirror of the PostgreSQL `wiki` schema (pg_schema.py::WIKI_SCHEMA_DDL).

SQLite has no schema namespaces, so `wiki.<table>` is flattened to
`wiki_<table>`; sqlite_sql_translate._translate_sql rewrites the SQL on the
way in (imported by sqlite_compat.py, issue #260), which is what lets the
52 modules that query these tables run unmodified on both backends.

Type mapping applied here (issue #206):

| PostgreSQL                  | SQLite                              |
|-----------------------------|-------------------------------------|
| BIGSERIAL / SERIAL PK       | INTEGER PRIMARY KEY AUTOINCREMENT   |
| TIMESTAMPTZ [DEFAULT NOW()] | TEXT [DEFAULT (datetime('now'))]    |
| JSONB                       | JSON  (decltype -> json.loads)      |
| INTEGER[] / BIGINT[]        | JSON  (decltype -> json.loads)      |
| BOOLEAN                     | INTEGER (0/1)                       |
| vector(384)                 | BLOB (no ANN index; see note)       |

The `JSON` decltype is load-bearing, not decorative: `sqlite_store` connects
with `detect_types=PARSE_DECLTYPES` and registers a converter for it, so
`entity_ids` comes back a `list[int]` exactly as psycopg returns an
`INTEGER[]`. Without it the column would return the string "[1,2]", which
call sites like wiki_emerge.py:220 (`for eid in c.get("entity_ids") or []`)
would iterate CHARACTER-WISE — silently producing garbage entity ids rather
than failing. Verified 2026-07-27.

`vector(384)` columns are kept as BLOB for column parity (`SELECT embedding`
resolves) but carry no ANN index: pgvector's HNSW has no SQLite equivalent,
and the sqlite-vec path used for `memories` needs a separate vec0 virtual
table. No wiki pipeline handler reads these columns today. GIN indexes are
likewise dropped — SQLite has no equivalent.

````

### module: completeness audit

````text
SQLite mirror of the PostgreSQL `wiki` schema (pg_schema.py::WIKI_SCHEMA_DDL).

SQLite has no schema namespaces, so `wiki.<table>` is flattened to
`wiki_<table>`; sqlite_sql_translate._translate_sql rewrites the SQL on the
way in (imported by sqlite_compat.py, issue #260), which is what lets the
52 modules that query these tables run unmodified on both backends.

Type mapping applied here (issue #206):

| PostgreSQL                  | SQLite                              |
|-----------------------------|-------------------------------------|
| BIGSERIAL / SERIAL PK       | INTEGER PRIMARY KEY AUTOINCREMENT   |
| TIMESTAMPTZ [DEFAULT NOW()] | TEXT [DEFAULT (datetime('now'))]    |
| JSONB                       | JSON  (decltype -> json.loads)      |
| INTEGER[] / BIGINT[]        | JSON  (decltype -> json.loads)      |
| BOOLEAN                     | INTEGER (0/1)                       |
| vector(384)                 | BLOB (no ANN index; see note)       |

source: ADR-0603
````
