---
created: 2026-09-16T07:03:29Z
kind: adr
number: 1070
status: accepted
tags: [wiki, curation, validation, issue-587]
title: A draft section carries a heading and a body, both text
---
# ADR-1070: A draft section carries a heading and a body, both text

## Status

accepted

## Context

`_validate_against_contract` (`mcp_server/handlers/wiki_refine.py`) checked two things about the sections a caller submits: that every heading the kind requires is present, and that no body is blank. It never checked a section's own heading. For a kind that declares no required section, a section such as `{"heading": "   ", "body": "real prose"}`, or `{}` itself, passed validation and was written to the draft (issue #587). The published Markdown drops such a section, since `core/draft_compiler.py` skips a section with no heading, but `handlers/wiki_compile.py` mirrors the draft's sections into `wiki.pages.sections` with no such guard, so the page row keeps the prose under an empty key.

The tool's `inputSchema` declares `required: [heading, body]` for a section, but the client-visible schema is derived from the registered wrapper's signature, `list[dict[str, Any]] | None`, and `_tool_meta.apply_param_docs` only merges descriptions into it. That nested `required` is therefore documentation, not enforcement, and a section missing its heading is a reachable client input. The review of PR #586 demonstrated both shapes end to end on a `note` draft.

The same two lines called `.strip()` on whatever the keys held, so a section sending a number for its heading or body raised `AttributeError` inside the handler instead of returning a validation error.

ADR-1069 refuses an empty value for the four top-level content fields. A section whose heading is empty is the same defect one level down.

## Decision

A section carries a heading and a body, each non-blank text. `_is_text` states that shape once, and `_validate_against_contract` reports, per section, a heading that is not text and a body that is not text. A section whose heading is not text is named by its index, since it has no name to quote. A blank heading no longer counts toward a required section either: the heading set the required-section check reads is built from headings that are text.

The handler already refuses a call whose sections fail validation before any write, so a refused call still touches neither the draft nor `wiki.memos`.

## Consequences

Easier: a published page cannot carry an untitled section, and a malformed section returns a validation error instead of an `AttributeError`.

`tests_py/handlers/test_wiki_refine_sections.py` drives the validator directly: an empty section, a missing heading, a blank heading, a non-text heading, four body shapes including a number, a well-formed section, and a blank heading against a required one. `test_a_headless_section_writes_nothing_even_without_a_contract` drives the handler on SQLite with a kind contract carrying no required section and asserts the sections column, `synth_model` and the memo count are unchanged. Six of those fail on the previous validator.

Harder: a caller that used a section as an untitled block of prose has to give it a heading. Nothing did: the tool has been registered only since ADR-1066.
