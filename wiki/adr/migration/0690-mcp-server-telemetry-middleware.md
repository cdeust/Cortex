---
title: "ADR-0690 — mcp_server/telemetry_middleware.py rationale"
status: accepted
source: mcp_server/telemetry_middleware.py
---

# ADR-0690 — mcp_server/telemetry_middleware.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
The SDK converts handler exceptions to TextContent inside call_next. Measuring
here includes those errors without reconstructing SDK messages or changing tool
results. Source: mcp 2.0.0 MCPServer._handle_call_tool and ServerMiddleware.

````
