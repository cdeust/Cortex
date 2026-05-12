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
    {"notes", "specs", "conventions", "lessons", "guides", "files"}
)

LEGACY_KIND_TO_MODERN: Final[dict[str, str]] = {
    "notes": "explanation",
    "specs": "rfc",
    "conventions": "explanation",
    "lessons": "explanation",
    "guides": "how-to",
    "files": "reference",
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
        self.validate()

    def validate(self) -> None:
        """Raise ValueError (with did-you-mean) if any axis violates the schema."""
        # Local import avoids importing the registry at module-load time
        # (the registry reads the wiki on first call).
        from mcp_server.core.wiki_axis_registry import (
            AXIS_AUDIENCE,
            AXIS_KIND,
            AXIS_LIFECYCLE,
            AXIS_PROVENANCE,
            did_you_mean,
            get_registry,
        )

        reg = get_registry()

        # Kind ───────────────────────────────────────────────────────
        if not reg.has(AXIS_KIND, self.kind):
            suggestions = did_you_mean(AXIS_KIND, self.kind, reg)
            raise ValueError(_format_unknown(AXIS_KIND, self.kind, suggestions))

        # Lifecycle ──────────────────────────────────────────────────
        # Lifecycle value must exist and must apply to this kind.
        lc = reg.get(AXIS_LIFECYCLE, self.lifecycle)
        if lc is None:
            suggestions = did_you_mean(AXIS_LIFECYCLE, self.lifecycle, reg)
            raise ValueError(
                _format_unknown(AXIS_LIFECYCLE, self.lifecycle, suggestions)
            )
        if lc.applies_to_kinds and self.kind not in lc.applies_to_kinds:
            raise ValueError(
                f"lifecycle {self.lifecycle!r} does not apply to kind "
                f"{self.kind!r} (only to {sorted(lc.applies_to_kinds)})"
            )
        if not lc.applies_to_kinds and self.kind == "adr":
            # ADRs must use the kind-specific subset.
            adr_lc = [
                v.name
                for v in reg.values(AXIS_LIFECYCLE)
                if "adr" in v.applies_to_kinds
            ]
            raise ValueError(
                f"kind=adr requires a lifecycle from {sorted(adr_lc)}; "
                f"got {self.lifecycle!r}"
            )

        # Audience ───────────────────────────────────────────────────
        if not self.audience:
            raise ValueError("audience must not be empty")
        for a in self.audience:
            if not reg.has(AXIS_AUDIENCE, a):
                suggestions = did_you_mean(AXIS_AUDIENCE, a, reg)
                raise ValueError(_format_unknown(AXIS_AUDIENCE, a, suggestions))

        # Provenance ─────────────────────────────────────────────────
        prov = reg.get(AXIS_PROVENANCE, self.provenance)
        if prov is None:
            suggestions = did_you_mean(AXIS_PROVENANCE, self.provenance, reg)
            raise ValueError(
                _format_unknown(AXIS_PROVENANCE, self.provenance, suggestions)
            )
        if prov.requires_generator and self.generator is None:
            raise ValueError(
                f"provenance={self.provenance!r} requires a Generator block"
            )

    def to_frontmatter(self) -> dict[str, object]:
        """Render this classification as a YAML-compatible frontmatter dict."""
        fm: dict[str, object] = {
            "kind": self.kind,
            "lifecycle": self.lifecycle,
            "audience": list(self.audience),
            "provenance": self.provenance,
        }
        if self.generator is not None:
            fm["generator"] = {
                "model": self.generator.model,
                "version": self.generator.version,
                "prompt_template": self.generator.prompt_template,
                "generated_at": self.generator.generated_at,
            }
        if self.tags:
            fm["tags"] = list(self.tags)
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
    from mcp_server.core.wiki_axis_registry import AXIS_KIND, get_registry

    return frozenset(get_registry().names(AXIS_KIND)) | LEGACY_KINDS
