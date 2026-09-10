---
kind: adr
number: 0553
title: Preserve pg_store_memory_domain design decisions
status: accepted
---

# ADR-0553: pg_store_memory_domain design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_memory_domain.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Reads domain-less memory rows (``current_memories`` — chain heads only,
matching the audit's own scope) and rewrites their ``domain``/``tags``
columns. Split into its own module (rather than added to an existing
``pg_store_*`` file) to keep each infrastructure file focused and under
the size cap — mirrors ``pg_store_wiki_domain.py``'s precedent for the
same problem shape (ADR-0051 Volet 4, commit 4ea13310).
````

### module, original line 1

````text
Every write here is guarded by ``WHERE (domain IS NULL OR domain = '')``
at the SQL level, not just in the caller: a concurrent write racing this
campaign can never be clobbered, and re-running the same UPDATE after it
already applied is a no-op (idempotence by construction, not by
application-level bookkeeping).

````

### list_domainless_memories, original line 35

````text
Active (chain-head) memories whose domain is empty, with evidence.
````

### list_domainless_memories, original line 35

````text
    Pre-condition:  ``limit`` bounds the per-cycle/per-run scan.
    Post-condition: every returned row carries ``id``, ``directory_context``
                    (``''`` if unset) and ``tags`` (JSON-decoded to a
                    Python list by psycopg's jsonb adapter). Scoped to
                    ``current_memories`` (superseded_by_id IS NULL) —
                    the same view the I6-D3 acceptance-criterion SQL
                    queries. By default, rows already carrying the
                    ``domain-orphan`` tag are excluded: an orphan is a
                    terminal, explicit state (I6-D3 rejects a sentinel
                    domain value, so the tag is the only signal that the
                    row was already processed) — without this exclusion
                    every re-run would re-select and re-journal every
                    orphan forever, breaking the idempotence contract
                    even though no DB write would actually occur. Pass
                    ``include_orphans=True`` to deliberately re-scan
                    previously-orphaned rows — the correct move only
                    after a change to the resolution logic itself (e.g.
                    a domain_mapping.py fix) that could newly resolve
                    rows the old logic could not (INC6.2 worktree gap).
                    ``update_memory_domain`` strips the orphan tag on a
                    successful re-resolution, so a rescanned-and-resolved
                    row will not be re-selected as an orphan again.
    
````

### update_memory_domain, original line 77

````text
    Pre-condition:  ``memory_id`` refers to an existing ``memories`` row;
                    ``domain`` is non-empty.
    Post-condition: if the row's domain was ``NULL``/``''`` at UPDATE
                    time, it now equals ``domain``, the ``domain-orphan``
                    tag (if present — a previously-orphaned row now
                    resolving on a rescan, INC6.2) is removed from
                    ``tags``, and this returns ``True``. Otherwise the
                    row is untouched (some concurrent writer already gave
                    it a domain) and this returns ``False`` — never
                    overwrites a non-empty domain. The tag removal is a
                    no-op (jsonb ``-`` on an absent element) for rows
                    that were never orphan-tagged, so this is safe to
                    call unconditionally for both first-pass fills and
                    orphan-rescan fills.
    
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
