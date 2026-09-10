# ADR-0455: mcp_server/handlers/wiki_consolidate.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_consolidate.py`; original SHA-256 `e4a6945f496899d712933f2fbb097211025916609931a89d92aa3f5f3b732e56`.

## Original docstring, lines 1–23

````text
"""Wiki Phase 4 — Thermodynamic consolidation sweep.

Runs three passes over wiki.pages:

  1. Heat decay + lifecycle transitions (active → area → archived,
     archived → active on revival).
  2. Staleness brake — pages whose file references no longer exist
     get is_stale=True; pages whose refs all came back get
     is_stale=False (auto-recovery). Also persists the harvested refs
     as wiki.page_sources rows (link_kind='references', ADR-0051 STEP 4)
     so the file <-> wiki graph exposes not just the one 'documents'
     primary but every file a page cites.
  3. Memo every transition for the audit trail.

Modes:
  full sweep:   wiki_consolidate({})
  dry-run:      wiki_consolidate({"dry_run": true})
  partial:      wiki_consolidate({"limit": 500})
  skip stale:   wiki_consolidate({"skip_staleness": true})

Composition root only — wires core/wiki_thermodynamics + core/
wiki_staleness against pg_store_wiki + filesystem.
"""
````

