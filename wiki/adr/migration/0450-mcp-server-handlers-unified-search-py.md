# ADR-0450: mcp_server/handlers/unified_search.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/unified_search.py`; original SHA-256 `d3b7b6f7a86174a0018ae6e2369f1254d4a18930abe24bca4912f67c18cb7f87`.

## Original docstring, lines 1–20

````text
"""Handler: unified_search — RRF-fuse Cortex memory recall with AP code
search (ADR-0046 Phase 3).

Composition root: cortex.recall (semantic memory) + ap.search_codebase
(code symbols) → core.unified_search_fusion → single ranked list.

When AP is off, the handler returns Cortex-only results marked
``status: partial, sources: [cortex]`` — never fails. When Cortex
returns nothing and AP is on, the response is the AP-only hits.
When AP is on but the per-call attempt itself fails (timeout, transport
error, not installed), ``status`` is also ``partial`` and ``degraded``
names the source and reason — this is distinct from AP genuinely
returning zero hits, which stays ``status: ok, degraded: null``.

The fusion contract: each input list must present unique string ids.
- Memories use ``memory:<memory_id>`` (added by this handler).
- AP symbols use ``symbol:<file>::<qualname>`` (added by the infra
  layer).
Ids never collide across sources.
"""
````

## Original schema description, interim lines 39–48

````text
Unified search across Cortex memories and the automatised-pipeline code graph (ADR-0046 Phase 3). Runs cortex.recall and ap.search_codebase in parallel, then merges via Reciprocal Rank Fusion (k=60, Cormack 2009). Returns a single ranked list with ``source_ranks`` on every record so the UI can explain where each hit came from. Falls back to Cortex-only when AP is disabled (CORTEX_MEMORY_AP_ENABLED=0) or unreachable (status=partial). An explicit project_root adds authored wiki pages matching every query token. Bare ADR-NNNN or exact_id queries resolve only the canonical wiki page, before memory/AP calls.
````

## Original schema description, interim lines 74–77

````text
Forwarded verbatim to cortex.recall's ADR-0054 spreading-activation opt-out (see recall's schema for detail). Defaults to false: cross-domain candidates the entity graph could reach stay excluded.
````

## Original schema description, interim lines 85–88

````text
Forwarded verbatim to cortex.recall's ADR-0054 addendum spreading-activation mode (see recall's schema for detail). Defaults to the benchmark-neutral ``tail`` mode.
````

