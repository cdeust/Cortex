# ADR-0461: mcp_server/handlers/wiki_list.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_list.py`; original SHA-256 `0092540392fb551cb9a7f75c2a178bfa0cf04c3bcf5290f6f766057e6b22e6de`.

## Original docstring, lines 1–13

````text
"""Handler: wiki_list — enumerate authored wiki pages.

Phase 3.2 of ADR-2244: redirect stubs are filtered from the listing by
default. Pass ``include_redirects: true`` to see them — useful for
migration tooling that needs to audit or clean up old paths.

Phase 5 of ADR-2244: auto-generated pages (frontmatter ``provenance:
auto-generated``, written by ``codebase_analyze``) are also filtered
from the listing by default. At ~8,700 pages they dominate any
listing, but they're lookup tables for code reference rather than
curated content; the default view should be human-authored content.
Pass ``include_auto_generated: true`` to see them.
"""
````

## Original docstring, lines 85–89

````text
"""Read frontmatter once; return (is_redirect_stub, is_auto_generated).

    Both filters share the same disk read and frontmatter parse — important
    because the default ``wiki_list`` walks ~9000 pages.
    """
````

## Original schema description, interim lines 20–35

````text
Enumerate every authored wiki page under ~/.claude/methodology/wiki/, filesystem-walked from the wiki root. Optionally restrict by kind (adr, specs, guides, reference, conventions, lessons, notes, journal, files). Two filters are applied by default and can be opted out of: (1) redirect stubs (frontmatter ``redirect_to:`` or ``redirect_id:``) are excluded — pass ``include_redirects: true`` to see them; (2) auto-generated pages (frontmatter ``provenance: auto-generated``, produced by ``codebase_analyze``) are excluded — pass ``include_auto_generated: true`` to see them. Read-only; never modifies anything. Distinct from `wiki_reindex` which generates the .generated/INDEX.md from the same enumeration, and from `wiki_read` which fetches one page's content. Latency <200ms on a 9000-page wiki because each page's frontmatter is read once for both filter checks. Returns {root, count, pages, redirect_count, auto_generated_count}.
````

