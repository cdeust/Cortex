---
title: "ADR-0700 — mcp_server/tool_registry_wiki.py rationale"
status: accepted
source: mcp_server/tool_registry_wiki.py
---

# ADR-0700 — mcp_server/tool_registry_wiki.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Registers the authoring surface that lets Claude maintain a first-class
Markdown wiki (ADRs, specs, file docs, notes) alongside PostgreSQL
memory. Pages are never derived from PG — they are authored via these
tools and indexed in PG as protected pointer memories for recall.
``wiki_migrate`` is the exception: it is the one-shot FS->PG sync +
ghost-reconciliation job (see ``mcp_server.handlers.wiki_migrate``),
exposed here so parity can be re-run and inspected without a shell.

````

## tool_wiki_write — original line 74 (docstring)

````text
Author a wiki page (create/append/replace) with the provided markdown.
````

## tool_wiki_read — original line 99 (docstring)

````text
        Phase 3.2 of ADR-2244: redirect stubs are followed transparently
        by default. Pass ``follow_redirects=False`` to read the stub itself.
        
````

## tool_wiki_verify — original line 207 (docstring)

````text
Verify wiki-page symbol citations against AP's code graph
        (ADR-0046 Phase 2).
````

## tool_wiki_rename — original line 241 (docstring)

````text
        Phase 3.2 of ADR-2244 — the building block for Phase 4 bulk renames.
        Requires the source page to have a stable frontmatter ``id`` (run
        ``scripts/wiki_backfill_ids.py --apply`` first).
        
````
