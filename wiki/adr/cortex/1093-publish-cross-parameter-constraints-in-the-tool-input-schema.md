---
created: 2026-10-07T12:00:00Z
kind: adr
number: 1093
status: accepted
tags: [mcp, tool-schema, recall_hierarchical, get_causal_chain]
title: Publish cross-parameter constraints in the tool input schema
---
# ADR-1093: Publish cross-parameter constraints in the tool input schema

## Status

accepted

## Context

`recall_hierarchical` requires `domain` or `memory_ids` (ADR-0045 R3), but
the client-visible schema listed only `query` as required and both other
parameters as nullable with default `null`. The client schema is derived by
the MCP SDK from the registered wrapper's signature
(`tool_registry_nav.py`); `_tool_meta.apply_param_docs` copies only parameter
descriptions onto it. The constraint therefore existed in prose only, agents
followed the schema, and the handler rejected the call (issue #661: 28 of 76
calls failed). `get_causal_chain` has the same shape (`entity_name` or
`memory_id`).

## Decision

1. A handler declares a cross-parameter constraint as a root-level JSON
   Schema combinator in its own `inputSchema` (`anyOf`, `oneOf`, `allOf`,
   `dependentRequired`), never through `required`. Each branch states what the
   handler really accepts, e.g. `{"required": ["domain"], "properties":
   {"domain": {"type": "string", "minLength": 1}}}`, so null, empty string and
   empty list fail the schema exactly as they fail the handler.
2. `_tool_meta.apply_input_constraints`, run by `register_all` after
   `apply_param_docs`, publishes a deep copy of those combinators on the
   signature-derived schema. It raises `ValueError` on any root keyword that is
   neither published nor signature-derived (`not`, `if`, `then`... would be
   dropped silently), on a branch keyword other than `required`/`properties`,
   and on any property a constraint mentions (`required` entries, `properties`
   keys, `dependentRequired` keys and values) that the wrapper does not expose.
3. Publication only: the SDK validates calls through pydantic against the
   wrapper signature, never against the published dict. Enforcement stays in
   the handler: `recall_hierarchical` raises `ValidationError`, `ingest_prd`
   raises `ValueError`; `get_causal_chain` returns an empty result with a
   message instead of raising (its published schema is stricter than its
   runtime behaviour, which is unchanged here).
4. `test_tool_schema_parity.py` asserts the root constraints every client
   receives equal those the handler declared; `test_input_constraints.py`
   covers each published keyword and each refusal.

Applied to `recall_hierarchical` (`domain` | `memory_ids`), `get_causal_chain`
(`entity_name` | `memory_id`) and `ingest_prd` (exactly one of `path`,
`content`, `pipeline_id`). Not declared: `validate_memory` and `narrative`
(neither scope is required: no scope validates all memories, respectively
narrates the hot memories) and `wiki_view` (its name|query|list rule is
enforced, but the tool is not registered in any tool registry, so nothing is
published).

## Rejected

- Defaulting `domain` from the working directory: `resolve_cwd` returns an
  empty string outside a known repository and the server cwd is not the
  client's project (`.mcpb`, Cowork), so the call would silently return empty.
- Making `domain` required in the wrapper: breaks the `memory_ids` path.
- A pydantic model validator: second enforcement point, and it emits no
  `anyOf`.

## Consequences

Whether a given client enforces `anyOf` before sending is not
verified here; the schema is the machine-readable contract, not a guarantee
of client behaviour. `ingest_prd` strips `path` and `pipeline_id` before
testing them, so a whitespace-only value passes the schema (`minLength: 1`) and
is rejected by the handler.
