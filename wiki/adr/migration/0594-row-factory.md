---
kind: adr
number: 0594
title: Preserve row_factory design decisions
status: accepted
---

# ADR-0594: row_factory design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/row_factory.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
``from psycopg.rows import dict_row`` at the top of such a module therefore
raises ``ModuleNotFoundError`` on the default backend — and because
``wiki_pipeline`` wraps each stage in try/except, that surfaced not as a crash
but as a logged stage error with zero output: the wiki pipeline silently did
nothing on every SQLite install. Found 2026-07-28 by running the full suite
against a genuinely psycopg-less environment (issue #220); the same class of
silent degradation as the FlashRank incident.
````

### module, original line 1

````text
* **PostgreSQL** — psycopg is installed, so this is exactly ``dict_row``, what
  every shared query already expects.
* **SQLite** — ``PsycopgCompatConnection.cursor()`` accepts ``row_factory``
  for signature parity and then IGNORES it, because that cursor already
  returns dict rows unconditionally (``sqlite_compat.py``, issue #206).
  ``None`` is therefore equivalent to ``dict_row`` there, not a downgrade.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
