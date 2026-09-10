---
title: "ADR-0636 — mcp_server/mcp_prompts.py rationale"
status: accepted
source: mcp_server/mcp_prompts.py
---

# ADR-0636 — mcp_server/mcp_prompts.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 1 (docstring)

````text
MCP prompts for Cortex — ``prompts/list`` + ``prompts/get`` (issue #176).
````

## module — original line 3 (docstring)

````text
Cortex registers ~51 tools but exposes no prompts, so every multi-tool
workflow it supports is discoverable only by reading docs or guessing — and
those are exactly the compositions where a caller gets the order wrong
(promotion episodic→semantic, wiki curation, session recall/onboarding). This
module publishes those compositions as protocol the client can enumerate.
````

## module — original line 9 (docstring)

````text
Source of truth (issue #176 criterion 3, the #98 drift class): a prompt step
names a tool and pulls that tool's one-line summary from the SAME handler
schema map (``SCHEMAS``) that ``tools/list`` is built from — never a second,
hand-maintained copy that can drift. ``test_mcp_prompts`` asserts every step
tool exists in that map.
````

## module — original line 15 (docstring)

````text
Profile awareness (issue #177): ``is_available`` decides whether a prompt is
offered under a profile — a prompt is offered iff the profile registers every
tool its workflow drives. So ``session_recall`` (all-lean tools) is offered in
both profiles, while ``promote_memories`` and ``curate_wiki`` (which drive the
full curation/consolidation surface) are hidden AND gated under ``lean`` by
``ToolProfileMiddleware``.
````

## module — original line 22 (docstring)

````text
Per-argument ``title``: the installed MCP SDK models a prompt argument as
``name``/``description``/``required`` only (``mcp.types.PromptArgument`` has no
``title`` field in this protocol version), so the human title is folded into
each argument's description rather than emitted as a separate field. The
prompt-level ``title`` IS emitted.

````

## session_recall — original line 232 (docstring)

````text
        mcp 2.0.0 migration (PR #331): argument descriptions moved from this
        docstring's Args: section into Annotated[..., Field(description=...)]
        on each parameter — mcp 2.0.0's func_metadata no longer parses
        Google-style docstrings for per-parameter descriptions the way
        FastMCP did (verified: no docstring-parsing logic anywhere in
        mcp.server.mcpserver.utilities.func_metadata, 2026-08-10). The
        docstring itself still supplies the prompt's own description.
        
````

## promote_memories — original line 261 (docstring)

````text
        See session_recall's docstring above for why argument descriptions
        live in Annotated[..., Field(...)] rather than an Args: section.
        
````

## curate_wiki — original line 282 (docstring)

````text
        See session_recall's docstring above for why argument descriptions
        live in Annotated[..., Field(...)] rather than an Args: section.
        
````
