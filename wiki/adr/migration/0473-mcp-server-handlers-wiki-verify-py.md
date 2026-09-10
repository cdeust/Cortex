# ADR-0473: mcp_server/handlers/wiki_verify.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_verify.py`; original SHA-256 `a872734388f1fc197b9524c5a9bb39f2d9bff19fc54241cf855ca650ba5e0abf`.

## Original docstring, lines 1–15

````text
"""Handler: wiki_verify — check whether a wiki page's cited symbols still
exist in the AP code graph (ADR-0046 Phase 2).

Composition root: filesystem wiki → symbol extractor (core) → AP bridge
verification (infrastructure) → verdict (core). Returns a structured
report per page.

When AP is disabled (``CORTEX_MEMORY_AP_ENABLED=0``), the handler
returns ``status: skipped`` with an explanation — never a staleness
claim. Graceful degradation is the invariant.

A single page or the entire wiki can be verified in one call. The
handler only READS the wiki; any flag persistence is the caller's
responsibility (there is no DB column for symbol_stale today).
"""
````

