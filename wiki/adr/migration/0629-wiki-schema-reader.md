---
kind: adr
number: 0629
title: Preserve wiki_schema_reader design decisions
status: accepted
---

# ADR-0629: wiki_schema_reader design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/wiki_schema_reader.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Port-and-adapter split (issue #126): ``mcp_server.shared.wiki_schema_loader``
declares the pure data model (``KindDefinition``, ``ClassifierRule``,
``ViewDefinition``, ``TriggerDefinition``, ``WikiRegistry``) and the pure
string-to-dataclass parsers. This module is the adapter — it walks the
wiki root on disk (``Path.rglob`` + ``read_text``) and feeds file content
through those parsers to build a ``WikiRegistry``.
````

### module, original line 1

````text
``wiki_schema_loader``/``wiki_pages`` moved ``core/`` -> ``shared/``
(layer fix: infrastructure/ must not import core/, and these parsers are
stdlib-only pure functions with no dependency on core's business rules —
same rationale as the #406 move). This module's own I/O
(``Path.rglob``/``read_text``) still lives here, never in ``core/`` or
``shared/``.
````

### module, original line 1

````text
Composition roots (``mcp_server/__main__.py``, and the wiki_curate /
wiki_synthesize / wiki_refine / wiki_view handlers) call ``load_registry``
directly with an explicit ``wiki_root`` — this module performs real I/O
and must never be imported from ``core/``.

````

### _load_folder_direct, original line 40

````text
    Used for reserved folders (``_kinds``, ``_rules``, ``_views``,
    ``_triggers``) that are not part of ``PAGE_KINDS``, so they are walked
    directly via ``rglob`` rather than through ``wiki_pages_listing.list_pages``.
    Never raises; a folder that doesn't exist yields an empty dict, and a
    file that fails to parse is skipped.
    
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
