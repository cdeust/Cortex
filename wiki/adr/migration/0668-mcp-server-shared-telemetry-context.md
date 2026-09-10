---
title: "ADR-0668 — mcp_server/shared/telemetry_context.py rationale"
status: accepted
source: mcp_server/shared/telemetry_context.py
---

# ADR-0668 — mcp_server/shared/telemetry_context.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
ContextVar scopes measurements to the current async task/thread. Reset tokens
also preserve the outer operation when an instrumented handler calls another.
Source: Python contextvars documentation, ContextVar.set/reset and asyncio support.

````

## set_retrieval_tier — original line 47 (docstring)

````text
Record the route actually executed, rather than inferring from intent.
````
