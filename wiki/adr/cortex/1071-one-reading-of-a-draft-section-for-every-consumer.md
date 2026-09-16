---
created: 2026-09-16T07:39:09Z
kind: adr
number: 1071
status: accepted
tags: [wiki, curation, compile, shared, issue-589]
title: One reading of a draft section for every consumer
---
# ADR-1071: One reading of a draft section for every consumer

## Status

accepted

## Context

A wiki draft's sections are read in four places, and each spelled out the shape for itself, with different answers (issue #589):

- `core/draft_compiler.py` skipped a section whose heading was falsy, so the published Markdown never carried an untitled section.
- `handlers/wiki_compile.py` built the `wiki.pages` mirror as a `{heading: body}` comprehension with no guard, so the same section landed in the row under an empty key. The file and its mirror disagreed about the same page. The review of PR #588 demonstrated it: a draft holding `sections=[{"heading": "", "body": "orphan prose"}]` compiled to a `.md` without the section and to `wiki.pages.sections == {"": "orphan prose"}`.
- `core/draft_curator.py::_missing_required_sections` called `.strip()` on whatever the section held, so a heading that was not text raised `AttributeError` inside `evaluate_draft`, and `getattr(s, "heading", None) or s.get("heading", "")` raised on a `Section` object whose heading was empty.
- `handlers/wiki_refine.py` had its own `_is_text` since ADR-1070, which is the only one of the four that was right.

A section arrives either as a dict, from an MCP client through `wiki_refine_draft`, or as a `Section` object from the template synthesizer, and ADR-1070 only closed the client entry point. A draft written before it, or by `wiki_synthesize`, still reaches the other three.

Two sections submitted with the same heading were also silently deduped by the mirror's mapping: the second body replaced the first with no error.

## Decision

`mcp_server/shared/wiki_sections.py` states the shape once: `is_text` for a non-blank string, `heading_of` returning the stripped heading or None, `body_of` returning the body or an empty string, and `titled_sections` returning the ordered `(heading, body)` pairs a page can carry. Being in `shared/`, it is reachable from core, handlers and infrastructure alike.

The Markdown renderer, the `wiki.pages` mirror and the curator's required-section lookup all read a draft through `titled_sections`, so the file, the row and the curation verdict describe the same page. `wiki_refine_draft` keeps refusing a malformed section at the entry point, and now also refuses two sections that carry the same heading, since the mirror cannot hold both.

## Consequences

Easier: a page row can no longer carry prose under an empty key, and the curator reports a malformed section as a missing required one instead of raising.

`tests_py/shared/test_wiki_sections.py` covers the four functions over dicts, `Section` objects, missing fields and non-text values. `tests_py/handlers/test_wiki_compile_sections_mirror.py` compiles a draft holding a blank heading, a missing heading and a numeric heading, and asserts the mirror holds only the titled section while the published Markdown omits the orphan prose. `tests_py/core/test_draft_curator_sections.py` drives four malformed shapes through `evaluate_draft`. `test_duplicate_headings_are_refused` covers the refine entry point. Three of those fail on the previous code, one of them with the `AttributeError`.

Changed, for malformed data only: the renderer used to coerce with `str()`, so a numeric heading rendered as `7` and a numeric body rendered under its heading. Both are now dropped, a whitespace-only body renders empty, and a padded heading renders stripped. A well-formed draft renders exactly as before, checked case by case against the previous loop.

Harder: a consumer that wanted the raw sections, with their unusable entries, has to read the draft column itself. None does.

Unchanged: what the synthesizer writes, and what `wiki_curate` decides for a well-formed draft.
