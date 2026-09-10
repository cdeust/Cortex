# ADR-0493: mcp_server/hooks/pipeline_impact_bump.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/pipeline_impact_bump.py`; original SHA-256 `8a60521fcda22188c2def070681f333f1a7fd1c2fc4fec4469c094d3754fd98e`.

## Original docstring, lines 2–32

````text
"""Claude Code PostToolUse hook — pipeline-driven heat bump on file edits.

When an agent edits or writes a file, this hook asks the upstream
ai-architect-mcp-codebase's ``detect_changes`` tool which symbols are
impacted by the edit, then boosts heat on memories tagged with those
symbol names. This is a targeted version of ``preemptive_context`` —
instead of substring-matching file path in ALL memories, we query the
codebase graph for the precise impact set.

Why both hooks coexist
----------------------
  * ``preemptive_context``: path-based, works without the pipeline, fires
    on every edit. Cheap, broad, sometimes imprecise.
  * ``pipeline_impact_bump``: graph-based, requires the pipeline MCP
    server, fires on every edit with a cooldown. Precise, narrower, skips
    cleanly when the pipeline isn't installed.

They compose: run ``preemptive_context`` for the baseline boost; this
hook then adds a *focused* boost on the pipeline-resolved impact set.

Cooldown
--------
Per-file 30s cooldown (shared file with ``preemptive_context`` via a
different lockfile). On a quick sequence of edits to the same file we
fire once per window, not per keystroke.

Paper backing
-------------
  * Collins & Loftus 1975 — spreading activation on a structured graph.
  * Smith & Vela 2001 — context reinstatement benefit (d=0.28).
"""
````

## Original comment, lines 77–78

````text
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Original comment, lines 219–219

````text
# issue #398: close cached stores on success, exception and SystemExit.
````

