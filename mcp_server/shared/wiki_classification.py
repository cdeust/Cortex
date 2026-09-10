"""Wiki classification 4-tuple — kind, lifecycle, audience, provenance + tags.

source: ADR-0676"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


# source: ADR-0676


# source: ADR-0676


LEGACY_KINDS: Final[frozenset[str]] = frozenset(
    {"notes", "specs", "conventions", "lessons", "guides", "files", "adrs"}
)

LEGACY_KIND_TO_MODERN: Final[dict[str, str]] = {
    "notes": "explanation",
    "specs": "rfc",
    "conventions": "explanation",
    "lessons": "explanation",
    "guides": "how-to",
    "files": "reference",
    # source: ADR-0676
    "adrs": "adr",
}


# ── Data model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Generator:
    """Full provenance block for ai/auto-generated content.

    Required when ``Classification.provenance`` is a registered value
    whose ``requires_generator`` is True (see
    ``mcp_server.core.wiki_axis_registry``).
    """

    model: str = ""
    version: str = ""
    prompt_template: str = ""
    generated_at: str = ""  # ISO-8601 UTC


@dataclass(frozen=True)
class Classification:
    """Represent wiki kind, lifecycle, audience, and provenance.

    source: ADR-0676

    Validation consults the runtime registry (``get_registry()``) rather
    than hardcoded Python sets. Adding a new value to any axis requires
    only writing ``wiki/_schema/<axis>/<name>.md``.

    source: ADR-0676
    """

    kind: str
    lifecycle: str
    audience: tuple[str, ...] = ("developer",)
    provenance: str = "human"
    generator: Generator | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # source: ADR-0676

        validate_classification(self)


def validate_classification(classification: "Classification") -> None:
    """Raise ValueError (with did-you-mean) if any axis violates the schema.

    source: ADR-0676"""
    # source: ADR-0676

    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — source: ADR-0676
        get_registry,
    )

    reg = get_registry()
    c = classification
    _validate_kind(reg, c)
    _validate_lifecycle(reg, c)
    _validate_audience(reg, c)
    _validate_provenance(reg, c)


def _validate_kind(reg, c: "Classification") -> None:
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — source: ADR-0676
        AXIS_KIND,
        axis_registry_has,
        did_you_mean,
    )

    if not axis_registry_has(reg, AXIS_KIND, c.kind):
        suggestions = did_you_mean(AXIS_KIND, c.kind, reg)
        raise ValueError(_format_unknown(AXIS_KIND, c.kind, suggestions))


def _validate_lifecycle(reg, c: "Classification") -> None:
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — source: ADR-0676
        AXIS_LIFECYCLE,
        axis_registry_get,
        axis_registry_values,
        did_you_mean,
    )

    lc = axis_registry_get(reg, AXIS_LIFECYCLE, c.lifecycle)
    if lc is None:
        suggestions = did_you_mean(AXIS_LIFECYCLE, c.lifecycle, reg)
        raise ValueError(_format_unknown(AXIS_LIFECYCLE, c.lifecycle, suggestions))
    if lc.applies_to_kinds and c.kind not in lc.applies_to_kinds:
        raise ValueError(
            f"lifecycle {c.lifecycle!r} does not apply to kind "
            f"{c.kind!r} (only to {sorted(lc.applies_to_kinds)})"
        )
    if not lc.applies_to_kinds and c.kind == "adr":
        # ADRs must use the kind-specific subset.
        adr_lc = [
            v.name
            for v in axis_registry_values(reg, AXIS_LIFECYCLE)
            if "adr" in v.applies_to_kinds
        ]
        raise ValueError(
            f"kind=adr requires a lifecycle from {sorted(adr_lc)}; got {c.lifecycle!r}"
        )


def _validate_audience(reg, c: "Classification") -> None:
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — source: ADR-0676
        AXIS_AUDIENCE,
        axis_registry_has,
        did_you_mean,
    )

    if not c.audience:
        raise ValueError("audience must not be empty")
    for a in c.audience:
        if not axis_registry_has(reg, AXIS_AUDIENCE, a):
            suggestions = did_you_mean(AXIS_AUDIENCE, a, reg)
            raise ValueError(_format_unknown(AXIS_AUDIENCE, a, suggestions))


def _validate_provenance(reg, c: "Classification") -> None:
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — source: ADR-0676
        AXIS_PROVENANCE,
        axis_registry_get,
        did_you_mean,
    )

    prov = axis_registry_get(reg, AXIS_PROVENANCE, c.provenance)
    if prov is None:
        suggestions = did_you_mean(AXIS_PROVENANCE, c.provenance, reg)
        raise ValueError(_format_unknown(AXIS_PROVENANCE, c.provenance, suggestions))
    if prov.requires_generator and c.generator is None:
        raise ValueError(f"provenance={c.provenance!r} requires a Generator block")


def classification_to_frontmatter(
    classification: "Classification",
) -> dict[str, object]:
    """Render a classification as a YAML-compatible frontmatter dict."""
    c = classification
    fm: dict[str, object] = {
        "kind": c.kind,
        "lifecycle": c.lifecycle,
        "audience": list(c.audience),
        "provenance": c.provenance,
    }
    if c.generator is not None:
        fm["generator"] = {
            "model": c.generator.model,
            "version": c.generator.version,
            "prompt_template": c.generator.prompt_template,
            "generated_at": c.generator.generated_at,
        }
    if c.tags:
        fm["tags"] = list(c.tags)
    return fm


def _format_unknown(axis: str, value: str, suggestions: tuple[str, ...]) -> str:
    """Human-readable validation error with did-you-mean hint."""
    if suggestions:
        return (
            f"unknown {axis}: {value!r}. Did you mean one of "
            f"{list(suggestions)}? Register a new value by writing "
            f"wiki/_schema/{axis}s/{value}.md."
        )
    return (
        f"unknown {axis}: {value!r}. No close matches in the registry. "
        f"Register a new value by writing wiki/_schema/{axis}s/{value}.md."
    )


# source: ADR-0676


def normalize_legacy_kind(kind: str) -> str:
    """Map a legacy kind name to its modern equivalent.

    source: ADR-0676
    """
    return LEGACY_KIND_TO_MODERN.get(kind, kind)


def is_legacy_kind(kind: str) -> bool:
    """Return whether the kind belongs to the legacy taxonomy.

    source: ADR-0676
    """
    return kind in LEGACY_KINDS


def all_known_kinds() -> frozenset[str]:
    """Modern (registered) + legacy kinds.

    source: ADR-0676
    """
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — source: ADR-0676
        AXIS_KIND,
        axis_registry_names,
        get_registry,
    )

    return frozenset(axis_registry_names(get_registry(), AXIS_KIND)) | LEGACY_KINDS
