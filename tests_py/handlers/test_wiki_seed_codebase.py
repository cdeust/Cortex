"""Tests for the wiki_seed_codebase producer (ADR-2244 Phase 6.2).

The seed handler imports markdown files (README, ADR, spec, convention,
lesson) from a repo into Cortex memory. Phase 6.2 fixed two producer
bugs:

  1. ``_kind_for`` used to return legacy kind names (``spec``,
     ``convention``, ``lesson``, ``note``). They now return modern
     kinds (``adr``, ``rfc``, ``explanation``) that match
     ``mcp_server.core.wiki_axis_registry`` tag-alias entries.

  2. The emitted tag list used ``kind:<value>`` which the classifier
     never read. The kind hint flowed nowhere. Tags now include the
     bare modern kind name plus ``imported`` so provenance routes
     correctly.

This test file pins the producer contract so a future refactor cannot
silently re-introduce the legacy shape.
"""

from __future__ import annotations

from mcp_server.handlers.wiki_seed_codebase import _kind_for


# ── Path → modern kind mapping ────────────────────────────────────────


def test_adr_path_routes_to_adr() -> None:
    assert _kind_for("docs/adr/0001-pgvector.md") == "adr"
    assert _kind_for("ADR-007.md") == "adr"


def test_decision_path_routes_to_adr() -> None:
    assert _kind_for("docs/decisions/use-pgvector.md") == "adr"


def test_architecture_path_routes_to_rfc() -> None:
    """ADR-2244 §4.1: ``spec`` → modern ``rfc`` for pre-decision design."""
    assert _kind_for("docs/architecture/overview.md") == "rfc"


def test_convention_path_routes_to_explanation() -> None:
    """Conventions/styles collapse into explanation per ADR-2244 §4.1."""
    assert _kind_for("docs/conventions/naming.md") == "explanation"
    assert _kind_for("docs/style-guide.md") == "explanation"


def test_lesson_path_routes_to_explanation() -> None:
    """Lessons / postmortems are root-cause explanations."""
    assert _kind_for("docs/lessons/cache-bug.md") == "explanation"
    assert _kind_for("docs/postmortems/2026-04-incident.md") == "explanation"


def test_readme_routes_to_explanation() -> None:
    """README is a conceptual orientation, not a decision/proposal."""
    assert _kind_for("README.md").lower() == "explanation"
    assert _kind_for("subdir/README.md").lower() == "explanation"


def test_unknown_path_defaults_to_explanation() -> None:
    """The new schema forbids bare ``notes`` as a kind — defaults route
    to ``explanation`` per ADR-2244 §4.1."""
    assert _kind_for("docs/random.md") == "explanation"


# ── Returned values are registry-registered tag aliases ────────────────


def test_all_returned_kinds_are_registered() -> None:
    """The whole point of Phase 6.2: every value ``_kind_for`` returns
    must be a tag alias the classifier actually reads. If a refactor
    introduces a value the registry doesn't know about, the kind hint
    silently flows nowhere — that's the bug Phase 6.2 fixed.
    """
    from mcp_server.core.wiki_axis_registry import (
        AXIS_KIND,
        build_default_registry,
    )

    reg = build_default_registry()
    # Gather every tag alias across all registered kinds.
    all_aliases: set[str] = set()
    for value in reg.values(AXIS_KIND):
        all_aliases.update(value.tag_aliases)
        all_aliases.add(value.name)

    sample_paths = [
        "ADR-001.md",
        "docs/architecture/x.md",
        "conventions/naming.md",
        "lessons/incident.md",
        "README.md",
        "docs/random.md",
    ]
    for path in sample_paths:
        kind = _kind_for(path)
        assert kind in all_aliases, (
            f"_kind_for({path!r}) returned {kind!r} which is not a "
            f"registered kind name or tag alias — the classifier won't "
            f"route it"
        )
