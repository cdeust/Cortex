# ADR-0793: scripts/wiki_pilot_migration.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/wiki_pilot_migration.py`; original SHA-256 `17c4ce181e6f896c56a68e6c13692ae47068b257b4f09a4eb81eb1d691a092f7`.

## Original docstring, lines 2–27

````text
"""Pilot migration analyzer — Phase 2 of ADR-2244.

Walks the methodology wiki, runs each page's body through the new
data-driven classifier (``mcp_server.core.wiki_classifier.classify_memory``,
post-#27/#28), and produces a Markdown report showing the proposed
modern 4-tuple (kind, lifecycle, audience, provenance) for each page
alongside its current legacy ``kind``.

Goal: human-reviewable accuracy check before any bulk re-bucketing
(Phase 4). The ADR-2244 acceptance criterion is ≥ 90% kind agreement
with human judgment on a ~100-page representative sample.

Usage
-----

    uv run scripts/wiki_pilot_migration.py \\
        --wiki ~/.claude/methodology/wiki \\
        --sample-size 100 \\
        --out scripts/wiki-pilot-report.md

By default samples are stratified across the current ``kind`` directories
so the report exercises ADRs, specs, lessons, notes, references, etc.
without being swamped by the 7,820 file-doc notes.

Read-only. The script never writes to the wiki itself.
"""
````

## Original docstring, lines 133–137

````text
"""Pull tags from frontmatter.

    Accepts the value as ``list[str]`` (block list, inline list) or
    ``str`` (comma-separated scalar). Empty/missing → ``[]``.
    """
````

## Reviewed remaining docstring (scripts/wiki_pilot_migration.py, interim lines 2–14)

````text
Pilot migration analyzer — Phase 2 of ADR-0793.

Usage
-----

    uv run scripts/wiki_pilot_migration.py \
        --wiki ~/.claude/methodology/wiki \
        --sample-size 100 \
        --out scripts/wiki-pilot-report.md

Read-only. The script never writes to the wiki itself.

source: ADR-0793
````


## Generated report heading

The historical report heading was `# ADR-2244 Phase 2 — Pilot migration report`.
It now cites this canonical decision page; the former identifier is retained
here as historical text and is not an active identity.
