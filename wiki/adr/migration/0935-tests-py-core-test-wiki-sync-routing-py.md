# ADR-0935: tests_py/core/test_wiki_sync_routing.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/core/test_wiki_sync_routing.py`, original SHA-256 `70feb1b862b8d82c5e75c23e09dd54ec0ef7e57bbd3b92af0b7983fc3e8eb92b`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–6

````text
"""Tests for ADR-2244 routing in wiki_sync.build_from_memory.

Verifies that the modern (kind, lifecycle, audience, provenance) tuple
drives the directory, that the frontmatter shape conforms to the new
schema, and that the file→notes/ misroute bug (Task #8) is fixed.
"""
````

## Original docstring, lines 46–46

````text
"""ADR-2244 §4.1: 'lesson' is dropped; root-cause goes to explanation/."""
````

## Original docstring, lines 86–87

````text
"""ADR-2244 §4: every modern page carries kind, lifecycle, audience,
    provenance in its frontmatter."""
````

## Original docstring, lines 117–121

````text
"""Phase 3 of ADR-2244: every page written by wiki_sync gets a UUID4
    id in its frontmatter so the path can later be moved without losing
    the page's identity. The id is required for redirect stubs that
    preserve inbound links during bulk migration.
    """
````

## Original docstring, lines 169–177

````text
"""Policy 2026-05-17 (superseded ADR-2244 Phase 6 admission):
    ``codebase`` / ``code-reference`` tags mark per-file extractor
    output that bloats the wiki — they stay in PG memory only.
    Coverage of the codebase flows through the structural scope
    pages (architecture / services / api / data-flow / code-walkthrough
    per project) the autonomous worker authors — not via per-file
    auto-generated dumps. ``build_from_memory`` returns None so no
    wiki page is written.
    """
````

