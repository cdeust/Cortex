# ADR-0471: mcp_server/handlers/wiki_seed_codebase.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_seed_codebase.py`; original SHA-256 `1835ad61c3ade58e521ccbe23bff0a358eebe01b031f3d35be325a8df8174a42`.

## Original docstring, lines 1–19

````text
"""Seed the wiki from a project's existing markdown docs (Phase 7.3).

Purpose: first-run users get concrete pages in their wiki within
minutes of install, without waiting for session-derived memories to
accumulate.

Scanned by default:
  README.md, CHANGELOG.md, CONTRIBUTING.md, ARCHITECTURE.md,
  HISTORY.md, SECURITY.md, docs/**/*.md, ADR-*.md, adr/*.md

Each file becomes ONE memory (via remember), tagged `seed:codebase`
and the detected kind. The wiki pipeline is run afterward so the
imports produce claim events → concepts → drafts → pages in one call.

Per-file size capped at 8 kB (head-only — prevents a 50-page README
from flooding the extractor). Binary and huge files skipped.

Never raises per-file; collects errors in the summary.
"""
````

## Original comment, lines 126–128

````text
# Skip files larger than this (2 MB) — seed docs are prose, not blobs.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Original docstring, lines 146–157

````text
"""Map a seed-eligible markdown path to a *modern* (ADR-2244) kind.

    Returned values are themselves tag aliases registered in
    ``mcp_server.core.wiki_axis_defaults.DEFAULT_KINDS``, so emitting
    the value as a memory tag lets the classifier route the page to
    the correct kind directory.

    Before ADR-2244 Phase 6.2 this function returned legacy kinds
    (``spec``, ``convention``, ``lesson``, ``note``) and the call-site
    wrote them as ``kind:<value>`` tags — a shape the classifier never
    read. The kind hint flowed nowhere.
    """
````

## Original comment, lines 162–162

````text
# was: spec — modern: pre-decision design → rfc
````

## Original comment, lines 166–166

````text
# was: lesson
````

## Original comment, lines 241–245

````text
# ADR-2244 Phase 6.2: emit ``kind`` as a registered tag alias
            # (``adr`` / ``rfc`` / ``explanation``) so the classifier
            # actually routes the page; emit ``imported`` so provenance
            # resolves to ``imported`` (these are bulk-imported markdown
            # files, not human-authored fresh in the wiki).
````

