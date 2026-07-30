"""Wiki classification 4-tuple — kind, lifecycle, audience, provenance + tags.

Implements the schema from ADR-2244 (richer wiki classification).

**Open-world by design.** Per user direction 2026-05-12, the set of valid
values on each axis is *not* a hardcoded Python frozenset — it is loaded
from the registry in ``mcp_server.core.wiki_axis_registry``, which merges
Python defaults with user-editable files under ``wiki/_schema/<axis>/``.
Adding a new audience or lifecycle value is a wiki edit, not a code edit.

Validation policy: **reject + suggest**. An unknown value raises
``ValueError`` whose message proposes the closest registered name via
``difflib.get_close_matches`` (user direction 2026-05-12).

References:
    - ADR-2244 in the methodology wiki
    - docs/research/wiki-classification-survey.md (literature survey)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


# ── Legacy kind back-compat (read-time only) ────────────────────────────


# Legacy kinds — readable for backward-compat but never produced by new
# writes. The registry does not list these; ``normalize_legacy_kind``
# remaps them on read.
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
    # The wiki has a few pages under ``adrs/`` (plural) — observed during the
    # 2026-05-13 Phase 2 pilot. Treated as the same legacy kind as ``adr``.
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
    """4-tuple page classification per ADR-2244.

    Validation consults the runtime registry (``get_registry()``) rather
    than hardcoded Python sets. Adding a new value to any axis requires
    only writing ``wiki/_schema/<axis>/<name>.md``.

    Fields:
        kind: registered value on the ``kind`` axis (drives directory).
        lifecycle: registered value on the ``lifecycle`` axis;
            ADR-specific lifecycle values (proposed/accepted/rejected/
            superseded) carry ``applies_to_kinds=("adr",)`` in their
            registration so non-ADRs reject them and ADRs reject the
            universal lifecycle.
        audience: tuple of registered values on the ``audience`` axis.
            Multi-valued; must be non-empty.
        provenance: registered value on the ``provenance`` axis.
        generator: required when the provenance value's
            ``requires_generator`` flag is True.
        tags: free controlled-vocabulary tags.
    """

    kind: str
    lifecycle: str
    audience: tuple[str, ...] = ("developer",)
    provenance: str = "human"
    generator: Generator | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # __post_init__ is a dunder — mutmut skips the WHOLE decorated
        # ClassDef body regardless (`mutmut/mutation/file_mutation.py:236`),
        # so this call site carries no mutation coverage either way; kept
        # as a method (constructors need one) and calls the free function
        # below for the actual validation logic (issue #282).
        validate_classification(self)


def validate_classification(classification: "Classification") -> None:
    """Raise ValueError (with did-you-mean) if any axis violates the schema.

    A free function, not a method: mutmut categorically excludes the body
    of any `@dataclass`-decorated class (`mutmut/mutation/file_mutation.py:
    236`), so logic placed on `Classification` methods would carry zero
    mutation coverage no matter how the test loader names the module
    (issue #262 3rd pass; issue #282). Split per-axis (§4.2, 40-line cap)
    into `_validate_kind` / `_validate_lifecycle` / `_validate_audience` /
    `_validate_provenance` below — the pre-extraction `validate()` method
    was already 64 lines as a single block; this keeps the orchestrator
    short instead of just relocating the same oversized function.
    """
    # Local import avoids importing the registry at module-load time
    # (the registry reads the wiki on first call).
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — documented deferral: the registry reads the wiki on first call; a module-load import would also invert the shared->core layer rule at import time
        get_registry,
    )

    reg = get_registry()
    c = classification
    _validate_kind(reg, c)
    _validate_lifecycle(reg, c)
    _validate_audience(reg, c)
    _validate_provenance(reg, c)


def _validate_kind(reg, c: "Classification") -> None:
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — see validate_classification
        AXIS_KIND,
        axis_registry_has,
        did_you_mean,
    )

    if not axis_registry_has(reg, AXIS_KIND, c.kind):
        suggestions = did_you_mean(AXIS_KIND, c.kind, reg)
        raise ValueError(_format_unknown(AXIS_KIND, c.kind, suggestions))


def _validate_lifecycle(reg, c: "Classification") -> None:
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — see validate_classification
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
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — see validate_classification
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
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — see validate_classification
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


# ── Legacy helpers ──────────────────────────────────────────────────────


def normalize_legacy_kind(kind: str) -> str:
    """Map a legacy kind name to its modern equivalent. Returns input unchanged
    when already modern (registered) or unknown."""
    return LEGACY_KIND_TO_MODERN.get(kind, kind)


def is_legacy_kind(kind: str) -> bool:
    """True if the kind belongs to the pre-ADR-2244 taxonomy."""
    return kind in LEGACY_KINDS


def all_known_kinds() -> frozenset[str]:
    """Modern (registered) + legacy kinds. For read paths that must accept either."""
    from mcp_server.core.wiki_axis_registry import (  # noqa: PLC0415 — documented deferral: the registry reads the wiki on first call; a module-load import would also invert the shared->core layer rule at import time
        AXIS_KIND,
        axis_registry_names,
        get_registry,
    )

    return frozenset(axis_registry_names(get_registry(), AXIS_KIND)) | LEGACY_KINDS
