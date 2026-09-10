---
title: "ADR-0698 — mcp_server/tool_registry_memory.py rationale"
status: accepted
source: mcp_server/tool_registry_memory.py
---

# ADR-0698 — mcp_server/tool_registry_memory.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## tool_import_sessions — original line 317 (docstring)

````text
Import conversation history into the memory store.
````

## tool_import_sessions — original line 319 (docstring)

````text
        Always streams JSONL files via head+tail (ADR-0045 R2). The legacy
        ``full_read`` parameter was removed in v3.13.0 Phase 1 because it
        loaded entire JSONLs into Python memory (OOM path).
        
````

## tool_unified_search — original line 371 (docstring)

````text
RRF-fuse Cortex memory recall with AP code search (ADR-0046 P3).
````

## module — original line 60 (comment)

````text
# Connection-rooted scoping: when CORTEX_ROOT_AGENT_TOPIC is set the
# agent_topic parameter is omitted from the registered signature
# (MCPServer derives the input schema from the signature), so the model
# never sees it. The handler forces the root topic server-side.
````
