---
created: 2026-09-16T05:33:19Z
kind: adr
number: 1066
status: accepted
tags: [wiki, mcp-tools, registry, issue-579]
title: Expose the Path B draft tools from their own registry module
---
# ADR-1066: Expose the Path B draft tools from their own registry module

## Status

accepted

## Context

`mcp_server/handlers/wiki_refine.py` has held the two Path B handlers since ADR-0467: `handler_get` (`wiki_get_draft`) hands a caller a pending draft with its source claims and its kind contract, and `handler_refine` (`wiki_refine_draft`) takes the refined prose back and records an audit memo. Neither was ever registered as an MCP tool: `mcp_server/tool_registry_wiki.py` registers ten other wiki tools, and no commit in the repository's history registered these two. No client could call them, and `handler_get`'s own instructions told the caller to "call wiki_refine_draft", a tool `tools/list` never advertised (issue #579).

Path A (`wiki_synthesize`) fills `wiki.drafts` from routed claims at scale, and `wiki_curate` decides which drafts are ready to publish. Without Path B a draft can only be improved by re-running the template synthesizer, so the maintainer's store held 546 drafts all carrying `synth_model` `template_v1`.

`tool_registry_wiki.py` stands at 266 lines against the 300-line cap of the craftsmanship gate, and two registrations in the style of that file cost about sixty.

## Decision

The two tools are registered from a new module, `mcp_server/tool_registry_wiki_drafts.py`, wired into `__main__`'s `merged_schemas()` and `register_all()` beside the other registries. `wiki_get_draft` is annotated `READ_ONLY`; `wiki_refine_draft` is annotated `NON_IDEMPOTENT_WRITE`, since each call inserts an audit memo. Both are `interactive` in `handlers/latency_class.py`: one draft per call, no scan. Neither joins `LEAN_TOOL_NAMES`, so the lean profile is unchanged.

The standalone tool count moves from 52 to 54, and from 55 to 57 with both upstream integrations. `tests_py/test_main.py::test_standalone_baseline_is_54_tools` carries the pinned number that `scripts/check_doc_claims.py` reads, and every document stating a count is updated with it, as is the `docker_smoke.sh` floor.

## Consequences

Easier: a host can now refine a draft it reads, which is what ADR-0467 designed Path B to do. The tool descriptions state that refinement leaves the draft's confidence as its claims set it (ADR-1065), so a caller cannot read the pair as a promotion path.

`tests_py/handlers/test_wiki_draft_tools.py` holds the surface: both names present with their annotations, the listing and content arguments reaching the handlers through `mcp.call_tool`, and one refine call landing in a SQLite store. `tests_py/handlers/test_tool_schema_parity.py` already required the wrapper signatures to match the handlers' own `inputSchema` exactly, and does so for these two as well.

Harder: a third wiki registry module is one more place to look when tracing where a wiki tool is registered. The alternative was carrying `tool_registry_wiki.py` past the 300-line cap.

Unchanged: `handler_refine` writes no confidence, `wiki_curate` keeps deciding what publishes, and nothing calls Path B automatically.
