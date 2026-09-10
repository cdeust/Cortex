---
title: "ADR-0679 — mcp_server/shared/wiki_frontmatter_validation.py rationale"
status: accepted
source: mcp_server/shared/wiki_frontmatter_validation.py
---

# ADR-0679 — mcp_server/shared/wiki_frontmatter_validation.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Closes the corruption class that PR #104 (commit 53712df8) repaired
reactively at read-time inside ``wiki_pages.parse_page`` (dup-label
strip, quote strip). That fix made ``recall``/`wiki_read`` tolerant of
the two corruption signatures already on disk; it did nothing to stop
``write_governed_page`` (``mcp_server/handlers/wiki_write.py``) from
persisting caller-supplied markdown verbatim, so any new signature the
read-time parser doesn't yet know about would still land on disk
uncorrected.
````

## module — original line 12 (docstring)

````text
This module round-trips content through ``parse_page`` + ``render_page``
so what reaches disk is ALWAYS the canonical form — whatever
``parse_page`` already knows how to repair is repaired before the first
byte is written, not after. Issue #110 moved the call site of this
function from ``wiki_write.write_governed_page`` down to
``infrastructure.wiki_store.write_page`` itself, so normalization covers
every caller (governed or direct) rather than only the interactive
``wiki_write`` tool path — see that module's docstring for the contract
and ``tests_py/architecture/test_write_page_call_sites.py`` for the
audited list of direct callers. The read-time tolerance
(``wiki_pages.parse_page``'s scalar-branch repair) stays in place
unchanged as defense in depth for content written before this gate
existed.
````

## module — original line 26 (docstring)

````text
Deliberately does NOT duplicate ``parse_page``'s parsing state machine —
only the one shape it cannot repair (an unclosed frontmatter fence, which
would silently fold the intended body into misparsed frontmatter keys)
is detected and rejected here.

````

## _opens_frontmatter_fence — original line 55 (docstring)

````text
    Mirrors ``parse_page``'s own opening check (wiki_pages.py) exactly,
    so this gate and the parser agree on what counts as "has frontmatter".
    
````
