# ADR-0929: tests_py/core/test_wiki_classifier.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/core/test_wiki_classifier.py`, original SHA-256 `bbb665a11bc85f97717c5a7bcedd282cce1b2a2b17d8c0f63937e06b460b71d4`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 131–135

````text
"""ADR-2244 §4.1: the legacy 'lesson' kind maps to modern 'explanation'.

    Root-cause analysis is explanatory content — the 'lesson' bucket
    collapses into 'explanation' with audience=[developer].
    """
````

## Original docstring, lines 294–306

````text
"""Policy 2026-05-17 (superseded ADR-2244 Phase 6 admission):
    ``codebase`` / ``code-reference`` tags mark per-file extractor output
    from ``codebase_analyze``. They are valuable in PG memory (recall
    substrate, halo retrieval) but bloat the wiki — a single scan
    repeats one page per file per invocation (8734-page incident).

    Coverage of the codebase now flows through the structural scope
    pages (``architecture-overview``, ``services``, ``api``,
    ``data-flow`` per project) written via ``curate_wiki``'s
    coverage-driven jobs — not per-file dumps. The classifier
    rejects ``codebase``-tagged content here so the wiki layer never
    re-accumulates per-file pages.
    """
````

## Original docstring, lines 355–359

````text
"""Pilot 2026-05-13 found 8 of 8 RFC pages misrouted to ADR because
    they carried the ``architecture`` tag, which used to be in adr.tag_aliases.
    ``architecture`` was removed from adr aliases — those pages now stay RFC
    (or fall through to explanation if no other signal hits).
    """
````

## Original docstring, lines 371–379

````text
"""Policy 2026-05-17 (superseded ADR-2244 Phase 6 admission):
    output of ``codebase_analyze`` carries the ``codebase`` audit tag
    and stays in PG memory only. The wiki documents code structurally
    (architecture, services, api, data-flow per project, written by
    ``curate_wiki`` coverage jobs) — not via one page per scanned file.

    The 8734-page misroute the original ADR-2244 Phase 6 test guarded
    against is now prevented at admission, not at kind-routing.
    """
````

## Original docstring, lines 402–406

````text
"""Pilot 2026-05-13 found ADR-001 (zero dependencies) tagged ``security``
    audience because its body listed ``crypto`` among Node built-in modules.
    The security pattern now requires ``cryptograph(y|ic)`` — the full word —
    so a bare module name no longer fires the audience.
    """
````

## Original comment, lines 221–221

````text
# ── ADR-2244: modern-kind routing (tutorial / how-to / runbook / rfc / journal) ──
````

## Original comment, lines 290–290

````text
# ── ADR-2244: provenance and audience inference ────────────────────────
````

