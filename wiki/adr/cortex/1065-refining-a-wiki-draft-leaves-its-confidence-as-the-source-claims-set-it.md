---
created: 2026-09-15T22:21:47Z
kind: adr
number: 1065
status: accepted
tags: [wiki, curation, confidence, issue-578]
title: Refining a wiki draft leaves its confidence as the source claims set it
---
# ADR-1065: Refining a wiki draft leaves its confidence as the source claims set it

## Status

accepted

## Context

`handler_refine` (`mcp_server/handlers/wiki_refine.py`, the `wiki_refine_draft` handler of Path B, ADR-0467) wrote a fixed confidence of 0.85 into every draft it refined, and recorded the `refined_llm` audit memo with the same 0.85. No source backed the value; ADR-0467 preserved the file as it stood during issue #514 and records no threshold choice.

A draft's confidence is set by the template synthesizer as the mean confidence of its source claims, or 0.4 when no claim carries one (`mcp_server/core/draft_synthesizer.py`). The curator reads it as a gate: below `MIN_CONFIDENCE_APPROVE` (0.6) a draft gets a reason and can at best be held, below `MIN_CONFIDENCE_HOLD` (0.4) it is rejected (`mcp_server/core/draft_curator.py`). Rewriting a draft's prose therefore lifted it past the approve threshold whatever the evidence behind its claims (issue #578). A clearer text is not a better-supported one.

The handler is not registered as an MCP tool today (`mcp_server/tool_registry_wiki.py` registers ten other wiki tools, and no commit ever registered it). The maintainer's PostgreSQL store held one `refined_llm` memo on 2026-09-16, written on 2026-04-14 by a `test_runner_v1` run. The defect was latent.

## Decision

`handler_refine` no longer passes a confidence to `update_draft`, so a refined draft keeps the confidence it had. The `refined_llm` memo records that confidence, read from the draft before the update. Refinement changes the wording of a draft and never its confidence; a change of confidence has to come from a change in the claims or their evidence.

## Consequences

Easier: the curator's confidence gate means the same thing for a refined draft as for a template draft. `tests_py/handlers/test_wiki_refine_confidence.py` refines a draft set between the hold and approve thresholds on SQLite and checks that its confidence and the memo's are unchanged, and that `evaluate_draft` still reports the approve-threshold reason. All three tests fail on the previous handler.

Unchanged: Path B stays unregistered. Wiring `wiki_get_draft` and `wiki_refine_draft` into the MCP surface, or removing them, is a separate decision.

Harder: nothing measured. A caller that relied on refinement to promote a draft now has to raise the confidence of the underlying claims instead.
