"""Tests for wiki_axis_registry — open-world classification registry.

Verifies that:
  - Bootstrap defaults expose the seed values for every axis.
  - User-added markdown files under ``wiki/_schema/<axis>/<name>.md``
    extend the registry without code changes.
  - User entries override defaults with the same name.
  - ``match_axis`` returns values whose patterns or tag-aliases hit.
  - ``did_you_mean`` proposes close matches via difflib.
"""

from __future__ import annotations

from pathlib import Path


from mcp_server.core.wiki_axis_registry import (
    AXIS_AUDIENCE,
    AXIS_KIND,
    AXIS_LIFECYCLE,
    AXIS_PROVENANCE,
    AXES,
    build_default_registry,
    did_you_mean,
    load_axis_registry,
    match_axis,
    reset_registry,
)


# ── Default seed ───────────────────────────────────────────────────────


def test_default_registry_has_every_axis() -> None:
    reg = build_default_registry()
    for axis in AXES:
        assert reg.values(axis), f"axis {axis!r} has no default values"


def test_default_kinds_include_adr_runbook_explanation() -> None:
    reg = build_default_registry()
    names = reg.names(AXIS_KIND)
    assert "adr" in names
    assert "runbook" in names
    assert "explanation" in names


def test_default_lifecycle_has_seedling_and_adr_subset() -> None:
    reg = build_default_registry()
    names = reg.names(AXIS_LIFECYCLE)
    assert "seedling" in names
    # ADR-specific lifecycle values are present and carry applies_to_kinds.
    proposed = reg.get(AXIS_LIFECYCLE, "proposed")
    assert proposed is not None
    assert "adr" in proposed.applies_to_kinds


def test_default_provenance_has_requires_generator_flag() -> None:
    reg = build_default_registry()
    auto = reg.get(AXIS_PROVENANCE, "auto-generated")
    assert auto is not None
    assert auto.requires_generator is True
    human = reg.get(AXIS_PROVENANCE, "human")
    assert human is not None
    assert human.requires_generator is False


def test_default_per_axis_is_unique() -> None:
    """Exactly one ``default=True`` value per axis (per kind scope for lifecycle)."""
    reg = build_default_registry()
    for axis in (AXIS_KIND, AXIS_AUDIENCE, AXIS_PROVENANCE):
        defaults = [v for v in reg.values(axis) if v.default]
        assert len(defaults) <= 1, f"{axis} has multiple defaults: {defaults}"


# ── User extension flow (the whole point of the redesign) ─────────────


def test_user_can_register_new_audience_via_schema_file(tmp_path: Path) -> None:
    """Per user direction 2026-05-12: ``manage anything using regex and recognition``.

    Adding a brand-new audience value requires writing a markdown file —
    no Python edit.
    """
    schema_dir = tmp_path / "_schema" / "audiences"
    schema_dir.mkdir(parents=True)
    (schema_dir / "data-scientist.md").write_text(
        "---\n"
        "name: data-scientist\n"
        "axis: audience\n"
        "display_name: Data scientist\n"
        "patterns:\n"
        "  - '\\b(dataset|notebook|jupyter|pandas)\\b'\n"
        "tag_aliases:\n"
        "  - ds\n"
        "  - ml\n"
        "default: false\n"
        "---\n\n"
        "# Data scientist audience\n\n"
        "Pages targeting ML practitioners.\n"
    )

    reg = load_axis_registry(tmp_path)
    ds = reg.get(AXIS_AUDIENCE, "data-scientist")
    assert ds is not None
    assert ds.display_name == "Data scientist"
    assert any("dataset" in p.pattern for p in ds.patterns)
    assert "ds" in ds.tag_aliases


def test_user_file_can_override_default(tmp_path: Path) -> None:
    """A user file with the same name as a default replaces it."""
    schema_dir = tmp_path / "_schema" / "audiences"
    schema_dir.mkdir(parents=True)
    (schema_dir / "developer.md").write_text(
        "---\n"
        "name: developer\n"
        "axis: audience\n"
        "display_name: Software engineer (overridden)\n"
        "default: true\n"
        "---\n"
    )

    reg = load_axis_registry(tmp_path)
    dev = reg.get(AXIS_AUDIENCE, "developer")
    assert dev is not None
    assert dev.display_name == "Software engineer (overridden)"


def test_missing_schema_folder_yields_defaults_only(tmp_path: Path) -> None:
    """No ``_schema/`` directory → registry is just the bootstrap seed."""
    reg = load_axis_registry(tmp_path)
    default = build_default_registry()
    for axis in AXES:
        assert reg.names(axis) == default.names(axis)


def test_malformed_schema_file_is_skipped(tmp_path: Path) -> None:
    """A broken frontmatter file does not crash registry load."""
    schema_dir = tmp_path / "_schema" / "audiences"
    schema_dir.mkdir(parents=True)
    (schema_dir / "broken.md").write_text("no frontmatter, just body")
    (schema_dir / "valid.md").write_text(
        "---\nname: ops-prod\naxis: audience\ndisplay_name: Production operators\n---\n"
    )
    reg = load_axis_registry(tmp_path)
    # Valid file loaded; broken one ignored.
    assert reg.has(AXIS_AUDIENCE, "ops-prod")


# ── Detection (regex + tag aliases) ────────────────────────────────────


def test_match_axis_finds_kind_by_pattern() -> None:
    reg = build_default_registry()
    matches = match_axis(
        "When the alert fires, follow this runbook procedure.",
        tags=None,
        axis=AXIS_KIND,
        registry=reg,
    )
    assert "runbook" in matches


def test_match_axis_finds_audience_by_tag_alias() -> None:
    reg = build_default_registry()
    matches = match_axis("", tags=["sre"], axis=AXIS_AUDIENCE, registry=reg)
    assert "ops" in matches


def test_match_axis_lifecycle_filters_by_kind_for_adr() -> None:
    """ADR-specific lifecycle values only apply to kind=adr.

    Asking for lifecycle on kind=runbook should NOT return 'proposed'
    even though the content contains the word 'proposed'.
    """
    reg = build_default_registry()
    matches = match_axis(
        "the proposed deploy is delayed",
        tags=None,
        axis=AXIS_LIFECYCLE,
        registry=reg,
        restrict_to_kind="runbook",
    )
    assert "proposed" not in matches


def test_match_axis_lifecycle_adr_excludes_universal() -> None:
    """A kind=adr classification cannot land on lifecycle=seedling."""
    reg = build_default_registry()
    matches = match_axis(
        "this is a seedling page",
        tags=None,
        axis=AXIS_LIFECYCLE,
        registry=reg,
        restrict_to_kind="adr",
    )
    assert "seedling" not in matches


# ── did_you_mean suggester ─────────────────────────────────────────────


def test_did_you_mean_finds_close_match() -> None:
    reg = build_default_registry()
    suggestions = did_you_mean(AXIS_AUDIENCE, "developper", reg)
    assert "developer" in suggestions


def test_did_you_mean_returns_empty_for_unrelated_value() -> None:
    reg = build_default_registry()
    suggestions = did_you_mean(AXIS_AUDIENCE, "quantum-superposition", reg)
    assert suggestions == ()


# ── Registry cache reset (used by tests, classifier path) ─────────────


def test_reset_registry_picks_up_new_user_file(tmp_path: Path, monkeypatch) -> None:
    """After a user adds a schema file and calls reset_registry(), the
    next ``get_registry()`` reflects the change without restart."""
    schema_dir = tmp_path / "_schema" / "audiences"
    schema_dir.mkdir(parents=True)

    # Point WIKI_ROOT at our tmp wiki so the default get_registry picks
    # up the user file.
    monkeypatch.setattr("mcp_server.infrastructure.config.WIKI_ROOT", str(tmp_path))
    reset_registry()

    from mcp_server.core.wiki_axis_registry import get_registry

    reg_before = get_registry()
    assert not reg_before.has(AXIS_AUDIENCE, "pm")

    (schema_dir / "pm.md").write_text(
        "---\nname: pm\naxis: audience\ndisplay_name: Product manager\n---\n"
    )
    reset_registry()
    reg_after = get_registry()
    assert reg_after.has(AXIS_AUDIENCE, "pm")
