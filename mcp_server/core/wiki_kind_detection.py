"""ADR-2244 modern-kind / lifecycle / audience / provenance detection.

Extracted from ``wiki_classifier.py`` (issue #134, file exceeded the
500-line hard limit in coding-standards.md §4). This module assembles
the ADR-2244 4-tuple axes by delegating to
``mcp_server.core.wiki_axis_registry`` — the open-world registry that
lets users add new kinds/lifecycles/audiences/provenances by writing a
schema file instead of editing Python. ``wiki_classifier.classify_memory``
is the only caller.
"""

from __future__ import annotations

from mcp_server.core.wiki_axis_registry import (
    AXIS_AUDIENCE,
    AXIS_LIFECYCLE,
    AXIS_PROVENANCE,
    get_registry,
    match_axis,
)

# Legacy → modern kind mapping. This is a one-time backward-compat shim
# (the legacy classifier returns 5 kinds; the modern axis defines 8) and
# stays in code rather than the registry: it is *transformational*, not
# *configurable*. Per ADR-2244 §4.1.
LEGACY_KIND_MAP: dict[str, str] = {
    "adr": "adr",
    "lesson": "explanation",
    "convention": "explanation",
    "spec": "rfc",
    "note": "explanation",
    "reference": "reference",
}


def detect_modern_kind(
    content: str,
    tags: list[str] | None,
    legacy_kind: str,
) -> str:
    """Pick a modern kind for a content+tags pair.

    Strategy (registry-driven per user direction 2026-05-12):
      1. Ask the registry which kinds match content/tags via
         ``match_axis``. The first hit wins; users add new kinds (with
         their own detection patterns) by writing
         ``wiki/_schema/kinds/<name>.md``.
      2. If no registered kind matches, fall back to the legacy → modern
         map (lesson/convention/note → explanation; spec → rfc; adr/
         reference unchanged).

    The legacy fallback is intentional: the upstream
    ``wiki_classifier._classify_to_legacy_kind`` returns one of the 5
    legacy kinds when no registered pattern fires, so we always have a
    kind to assign.
    """
    from mcp_server.core.wiki_axis_registry import AXIS_KIND

    matches = match_axis(content, tags, AXIS_KIND, get_registry())
    if matches:
        return matches[0]
    return LEGACY_KIND_MAP.get(legacy_kind, "explanation")


def detect_provenance(tags: list[str] | None) -> str:
    """Pick a provenance value via the registry.

    Falls back to the default-flagged provenance value (``human`` in the
    bootstrap seed) when no pattern or tag matches. Users register new
    provenances by writing ``wiki/_schema/provenances/<name>.md``.
    """
    reg = get_registry()
    matches = match_axis("", tags, AXIS_PROVENANCE, reg)
    if matches:
        return matches[0]
    default = reg.default_for(AXIS_PROVENANCE)
    return default.name if default is not None else "human"


def detect_audiences(
    content: str, tags: list[str] | None, kind: str
) -> tuple[str, ...]:
    """Pick one or more audience values via the registry.

    Audience is multi-valued: a runbook may target ops + security. Any
    matching registered audience contributes. Falls back to the
    default audience when nothing matches.
    """
    reg = get_registry()
    matches = list(match_axis(content, tags, AXIS_AUDIENCE, reg))
    if not matches:
        default = reg.default_for(AXIS_AUDIENCE)
        if default is not None:
            matches.append(default.name)
        else:
            matches.append("developer")
    # Deduplicate preserving order.
    seen: set[str] = set()
    return tuple(x for x in matches if not (x in seen or seen.add(x)))


def pick_lifecycle(kind: str) -> str:
    """Pick the default lifecycle for a new page of the given kind.

    Asks the registry for the lifecycle value flagged ``default=true``
    among entries that apply to this kind. ADR-applicable lifecycle
    values are filtered separately so a non-ADR cannot inherit ``proposed``.
    """
    reg = get_registry()
    for v in reg.values(AXIS_LIFECYCLE):
        if v.default and (
            (kind == "adr" and "adr" in v.applies_to_kinds)
            or (kind != "adr" and not v.applies_to_kinds)
        ):
            return v.name
    # Last-resort hardcoded fallback (registry seed must always populate
    # at least one default per axis, so this is unreachable in practice).
    return "proposed" if kind == "adr" else "seedling"
