"""Wiki classification 4-tuple — kind, lifecycle, audience, provenance + tags.

Implements the schema from ADR-2244 (richer wiki classification).

Every wiki page is classified by an exclusive ``kind`` (one of 8 values, drives
directory) plus three orthogonal facets (lifecycle, audience, provenance) and
a free ``tags`` set. The 4-tuple replaces the previous single-kind taxonomy
that left 92% of pages stuck in the ``notes`` catch-all.

References:
    - ADR-2244 in the methodology wiki (adr/_general/2244-richer-wiki-classification.md)
    - docs/research/wiki-classification-survey.md (literature survey)
    - Diátaxis (diataxis.fr), DITA (dita-lang.org), Cloudflare style guide
    - Nygard/MADR for the ADR lifecycle subset (adr.github.io/madr)

Backward compatibility: legacy kinds (``notes``, ``specs``, ``conventions``,
``lessons``, ``guides``, ``files``) remain readable via ``LEGACY_KINDS`` and
``normalize_legacy_kind``. New writes go through the modern schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


# ── Closed enums (ADR-2244 §4) ───────────────────────────────────────────


# 8 exclusive kinds, each grounded in ≥3 surveyed taxonomies. Drives the
# directory under ``wiki/``: a page of kind ``adr`` lives in ``adr/...``.
KINDS: Final[frozenset[str]] = frozenset(
    {
        "tutorial",
        "how-to",
        "reference",
        "explanation",
        "adr",
        "runbook",
        "rfc",
        "journal",
    }
)


# Legacy kinds — readable but not produced by new writes. Migration target
# in ``LEGACY_KIND_TO_MODERN`` (see ADR-2244 §4.1 "Dropped from the kind axis").
LEGACY_KINDS: Final[frozenset[str]] = frozenset(
    {"notes", "specs", "conventions", "lessons", "guides", "files"}
)


# Migration map: legacy kind → modern kind. Used by read-time backward
# compat (wiki_read / wiki_list) so callers can normalize without seeing
# legacy directory names. ``specs`` is ambiguous (rfc or reference) and
# defaults to ``rfc``; per-page review may reroute it during Phase 4.
LEGACY_KIND_TO_MODERN: Final[dict[str, str]] = {
    "notes": "explanation",
    "specs": "rfc",
    "conventions": "explanation",
    "lessons": "explanation",
    "guides": "how-to",
    "files": "reference",
}


# Universal lifecycle states (apply to every kind except adr).
LIFECYCLES: Final[frozenset[str]] = frozenset(
    {"seedling", "draft", "active", "deprecated", "archived"}
)


# ADR-specific lifecycle subset (Nygard / MADR). The ADR lifecycle space
# is disjoint from the universal one — an ADR cannot be ``seedling``.
ADR_LIFECYCLES: Final[frozenset[str]] = frozenset(
    {"proposed", "accepted", "rejected", "superseded"}
)


# Closed audience enum (per user direction 2026-05-12).
AUDIENCES: Final[frozenset[str]] = frozenset(
    {"developer", "ops", "security", "internal", "external"}
)


# Closed provenance enum. ``ai-generated`` and ``auto-generated`` both
# require a ``Generator`` block (full provenance per user direction).
PROVENANCES: Final[frozenset[str]] = frozenset(
    {"human", "ai-generated", "imported", "auto-generated"}
)


_GENERATOR_REQUIRED_FOR: Final[frozenset[str]] = frozenset(
    {"ai-generated", "auto-generated"}
)


# ── Data model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Generator:
    """Full provenance block for ai/auto-generated content.

    Captures enough metadata to re-run the generator and debug bad outputs
    by model version. Mandatory when ``Classification.provenance`` is
    ``ai-generated`` or ``auto-generated``.
    """

    model: str = ""
    version: str = ""
    prompt_template: str = ""
    generated_at: str = ""  # ISO-8601 UTC, e.g. 2026-05-12T08:55:00Z


@dataclass(frozen=True)
class Classification:
    """4-tuple page classification per ADR-2244.

    Fields:
        kind: one of ``KINDS`` (exclusive; drives directory).
        lifecycle: one of ``LIFECYCLES`` (or ``ADR_LIFECYCLES`` for ``kind=adr``).
        audience: subset of ``AUDIENCES``, multi-valued. Defaults to ``("developer",)``.
        provenance: one of ``PROVENANCES``. Defaults to ``human``.
        generator: required when ``provenance`` ∈ {ai-generated, auto-generated}.
        tags: free controlled-vocabulary tags. Capped at ~50 in practice.

    Validation runs in ``__post_init__``; invalid tuples raise ``ValueError``
    at construction time so writers fail fast.
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
        """Raise ValueError if any axis violates the schema."""
        if self.kind not in KINDS:
            raise ValueError(
                f"unknown kind: {self.kind!r}; must be one of {sorted(KINDS)}"
            )
        valid_lifecycles = ADR_LIFECYCLES if self.kind == "adr" else LIFECYCLES
        if self.lifecycle not in valid_lifecycles:
            raise ValueError(
                f"invalid lifecycle {self.lifecycle!r} for kind={self.kind!r}; "
                f"must be one of {sorted(valid_lifecycles)}"
            )
        if not self.audience:
            raise ValueError("audience must not be empty")
        for a in self.audience:
            if a not in AUDIENCES:
                raise ValueError(
                    f"unknown audience: {a!r}; must be one of {sorted(AUDIENCES)}"
                )
        if self.provenance not in PROVENANCES:
            raise ValueError(
                f"unknown provenance: {self.provenance!r}; "
                f"must be one of {sorted(PROVENANCES)}"
            )
        if self.provenance in _GENERATOR_REQUIRED_FOR and self.generator is None:
            raise ValueError(
                f"provenance={self.provenance!r} requires a Generator block"
            )

    def to_frontmatter(self) -> dict[str, object]:
        """Render this classification as a YAML-compatible frontmatter dict.

        Audience is serialized as a list (multi-valued). The generator block
        is nested when present. Tags are a list.
        """
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


# ── Helpers ──────────────────────────────────────────────────────────────


def normalize_legacy_kind(kind: str) -> str:
    """Map a legacy kind name to its modern equivalent.

    Used by read-time backward compat: when ``wiki_list`` or ``wiki_read``
    surfaces a page whose frontmatter says ``kind: notes``, callers can
    treat it as ``kind: explanation`` for routing/display purposes
    without rewriting the page. Returns the input unchanged when already
    modern.
    """
    return LEGACY_KIND_TO_MODERN.get(kind, kind)


def is_legacy_kind(kind: str) -> bool:
    """True if the kind belongs to the pre-ADR-2244 taxonomy."""
    return kind in LEGACY_KINDS


def all_known_kinds() -> frozenset[str]:
    """Modern + legacy kinds. Useful for read paths that must accept either."""
    return KINDS | LEGACY_KINDS
