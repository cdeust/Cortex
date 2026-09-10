---
kind: adr
number: 0628
title: Preserve wiki_reindex_io design decisions
status: accepted
---

# ADR-0628: wiki_reindex_io design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/wiki_reindex_io.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of wiki_store.py (issue: 439 lines over the 300-line §4.1
cap, pre-existing before the layer-violation fix that also touched this
file) — regenerating ``.generated/INDEX.md``/``README.md`` and cleaning
up superseded id-prefixed pages is a distinct "post-write housekeeping"
concern from the write/read primitives (``write_page``/``read_page``)
that live in ``wiki_store.py``.

````

### _refresh_readme_if_safe, original line 24

````text
README half of ``try_reindex``: only overwrite if the file is
    absent or still carries the auto-generated marker — never clobber a
    hand-written README. An unreadable README also blocks the write
    (issue #197 sweep: falling through to overwrite on a read failure
    was the actual regression this guards against).
    
````

### try_reindex, original line 48

````text
    Produces three artefacts:
      * ``<root>/.generated/INDEX.md`` — structured TOC grouped by
        domain then kind (for tech readers).
      * ``<root>/README.md``           — plain-language top-level
        entry point (for non-tech readers); see ``_refresh_readme_if_safe``.
      * cleans up superseded ``{id}-{slug}.md`` files via
        ``cleanup_id_prefixed_pages``.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
