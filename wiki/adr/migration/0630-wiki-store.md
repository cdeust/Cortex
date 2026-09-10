---
kind: adr
number: 0630
title: Preserve wiki_store design decisions
status: accepted
---

# ADR-0630: wiki_store design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/wiki_store.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Wiki filesystem store — read/write primitives, never destructive.
````

### module, original line 1

````text
Operations:
    read_page       return the raw markdown or None if missing
    write_page      atomic write in create/append/replace modes
````

### module, original line 1

````text
Never deletes pages. Never regenerates content. Page listing/append
(``append_section``/``list_pages``/``next_adr_number``) lives in the
sibling ``wiki_pages_listing`` module and reindex (``.generated/
INDEX.md``/``README.md`` rebuild + superseded-page cleanup) in
``wiki_reindex_io`` — both split out (issue: 439 lines over the
300-line §4.1 cap, pre-existing before the layer-violation fix that
also touched this file).
````

### module, original line 1

````text
Issue #110: ``write_page`` is the true choke point for every wiki-tree
byte, not ``wiki_write.write_governed_page`` (that function's docstring
claimed otherwise pre-fix; corrected there). At least 7 handlers call
``write_page`` directly, bypassing ``write_governed_page``'s governance
side effects (pointer memory, citations) — deliberately, in most cases
(e.g. redirect stubs, generated reference pages) where that bookkeeping
does not apply. What those callers must NOT be able to bypass is
write-time frontmatter normalization (issue #107/PR #109): ``write_page``
itself now runs ``normalize_frontmatter`` on any full-page write
(``create``/``replace``; ``append``'s content is a fragment, never
normalized — same exclusion ``write_governed_page`` already documented),
so no caller, present or future, can persist a non-canonical frontmatter
shape.
````

### module, original line 1

````text
Layer note: this module's page-write dependency (``normalize_frontmatter``)
is pure, zero-I/O and lives in ``shared/`` (moved from ``core/``, issue:
infra may not import core). Promoting a memory to a wiki page DOES need
real domain judgment (the v2 classifier, ``core.wiki_sync.build_from_memory``)
— that call is made by the composition root,
``mcp_server.handlers.wiki_memory_sync``, which wires this module's
``write_page`` (pure I/O) to core's classification decision. This
module itself never imports ``core/``.

````

### safe_join, original line 67

````text
Resolve ``rel_path`` against ``root`` with inline CWE-22 sanitization.
````

### write_page, original line 137

````text
    precondition: for ``create``/``replace``, ``content`` is a FULL page
    (frontmatter + body, or plain body with no frontmatter) the caller
    intends to persist verbatim; for ``append``, ``content`` is a
    fragment appended below whatever is already on disk.
    postcondition: for ``create``/``replace``, the bytes actually written
    are always ``normalize_frontmatter(content)`` (issue #110) — this is
    the one choke point every wiki-tree write passes through, so no
    caller (governed via ``write_governed_page`` or direct) can persist a
    non-canonical frontmatter shape. ``append``'s fragment is never
    normalized (there is no frontmatter fence to canonicalize in a
    fragment, and treating one as a full page would corrupt it — see
    ``normalize_frontmatter``'s own precondition).
    raises: ``UnclosedFrontmatterError`` (from ``normalize_frontmatter``,
    propagated uncaught) for ``create``/``replace`` when ``content`` opens
    a frontmatter fence it never closes.
    
````

### _resolve_write_target, original line 172

````text
CWE-22 sanitization matching CodeQL's py/path-injection example
    VERBATIM (see ``read_page`` for references). Returns the sanitized
    absolute path string for ``write_page`` to use at every sink.
    
````

### _atomic_write_bytes_str, original line 219

````text
    Separate from ``_atomic_write_bytes`` so the string-based flow from
    ``write_page`` doesn't rebind through ``Path(...)`` — keeps the
    sanitizer→sink chain on the same variable for static analysis.
    
````

### comment, original line 91

````text
# os.path.commonpath on the pair — if they differ from the root, the
    # candidate has escaped. This is the pattern CodeQL matches as a
    # path-traversal sanitizer.
````

### comment, original line 118

````text
# Defence-in-depth against prefix-aliasing (base_path='/foo' matches
    # '/foobar'). CodeQL's example doesn't do this; we add it because
    # the containment check above is too permissive without a separator.
````

### comment, original line 123

````text
# fullpath is sanitized — sink uses the sanitized variable directly.
````

### comment, original line 163

````text
# fullpath is sanitized — use it directly at every sink.
````

### comment, original line 184

````text
# Defence-in-depth against prefix-aliasing.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
