# ADR-0470: mcp_server/handlers/wiki_resolve.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_resolve.py`; original SHA-256 `01baa66acd6d0c7005665dcdabdc00561ae502fba9935d827dc5d5bc554e7024`.

## Original docstring, lines 1–14

````text
"""Wiki Phase 2.2 — Resolve claim_events.

MCP tool entry point. Wires:
  - core/claim_resolver (pure logic, returns plans)
  - infrastructure/pg_store_wiki (entity lookup, batch updates, memo write)

Modes:
  resolve all unlinked: wiki_resolve({})
  resolve a slice:      wiki_resolve({"limit": 100})
  resolve one memory:   wiki_resolve({"memory_id": 42})

Composition root — never raises per-claim; collects errors in summary.
Idempotent at the row level (entity / supersedes updates skip no-ops).
"""
````

## Original comment, lines 112–118

````text
# "unresolved" = no entities linked yet. Expressed through
            # array_length rather than the PostgreSQL empty-array literal
            # '{}': that literal never matches SQLite's JSON '[]', so this
            # query returned zero rows on that backend and resolve was a
            # permanent no-op (issue #206). COALESCE covers both the empty
            # array (array_length -> NULL on PostgreSQL, 0 on SQLite) and
            # a NULL column, identically on both.
````

## Original comment, lines 197–197

````text
# Memo each supersedes + conflict for the audit trail
````

