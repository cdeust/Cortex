---
created: 2026-09-16T06:06:58Z
kind: adr
number: 1068
status: accepted
tags: [wiki, curation, contract, issue-583]
title: A wiki draft refinement must carry content
---
# ADR-1068: A wiki draft refinement must carry content

## Status

accepted

## Context

`handler_refine` (`mcp_server/handlers/wiki_refine.py`) treats `title`, `lead`, `sections` and `frontmatter` as optional, and `update_draft` skips every field that is `None`. `synth_model` is different: it defaults to `claude_refine_v1` and is always passed. A call carrying nothing but a `draft_id` therefore updated the row, returned `updated: true`, stamped the draft with a model that wrote none of its content, and inserted a `refined_llm` memo into `wiki.memos` recording a refinement that did not happen (issue #583).

The behavior predates the tool's exposure; the review of PR #581 found it. Since ADR-1066 registered `wiki_refine_draft`, any MCP client can make that call, so an audit trail meant to distinguish template synthesis from LLM refinement can now be filled with entries that refined nothing.

## Decision

A refinement carries content. When `title`, `lead`, `sections` and `frontmatter` are all absent, `handler_refine` returns `{"error": "nothing to refine: ...", "updated": false}` and writes nothing: no `synth_model`, no memo. The four field names live in one module constant, `_CONTENT_FIELDS`, which the error message names, and the tool description states the refusal.

## Consequences

Easier: every `refined_llm` memo in `wiki.memos` now corresponds to prose a model actually submitted, and a draft's `synth_model` names the model that wrote its content.

`tests_py/handlers/test_wiki_refine_confidence.py::test_a_refine_carrying_no_content_writes_nothing` calls the handler with only a `draft_id` and asserts the draft's `synth_model` and `lead` are unchanged, that the memo count for that draft is unchanged, and that the response is an error. It fails on the previous handler.

Harder: a caller that wanted to record a rationale or a `synth_prompt` alone now has to send content with it. No caller did: the tool has been registered only since ADR-1066, and the maintainer's store holds one `refined_llm` memo, from a test runner in April 2026.
