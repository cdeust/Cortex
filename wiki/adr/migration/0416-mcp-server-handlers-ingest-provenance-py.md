# ADR-0416: mcp_server/handlers/ingest_provenance.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/ingest_provenance.py`; original SHA-256 `5d226fcf09e2bc14500c32229e3432cb364b6f68886419bde082503b7ee1dc6b`.

## Original docstring, lines 1–24

````text
"""Ingestion provenance (ADR-0052 sec 2, INC5.2).

Two Cortex handlers write the same PostgreSQL rows from two different
engines: ``ingest_codebase`` (primary — pulls the ai-architect-mcp-codebase (AP)
graph via APBridge/mcp_client_pool) and ``codebase_analyze`` (explicit
fallback — native in-process tree-sitter AST, used only when AP is
unreachable). ADR-0052 sec 2 requires that:

1. every memory either path writes carries a provenance tag (``src:ap`` or
   ``src:native``), plus the AP binary version when ``src:ap`` applies;
2. ``codebase_analyze`` states explicitly whether it is running as the
   documented AP-unreachable fallback, or in violation of the documented
   precedence (AP is reachable but native ran anyway) — never silently;
3. ``ingest_codebase`` checks version parity between its two Cortex->AP
   client paths (``APBridge`` resolution vs the ``mcp_client_pool``
   ``mcp-connections.json`` "codebase" server) and surfaces divergence
   (iface angle-mort 5: a live skew was observed between a 0.4.0 symlinked
   binary and a manifest-declared 0.6.0 plugin).

This module is the single place both ingestion handlers get their
provenance tags and the parity check from — no writer computes a tag
string inline. Infrastructure I/O (APBridge, mcp_client_pool) is reached
the same way ``ingest_helpers.py`` already does from the handlers layer.
"""
````

## Original comment, lines 39–39

````text
# ── Provenance tags (ADR-0052 sec 2, requirement 1) ─────────────────────────
````

## Original comment, lines 45–45

````text
# ── Fallback-precedence tags (ADR-0052 sec 2, requirement 2) ────────────────
````

