"""Wiki axis registry — data-driven classification with extensible values.

User direction (2026-05-12): "having only 4 values for each is a band-aid
fix, we should be able to manage anything using regex and recognition."

This module replaces the hardcoded ``KINDS`` / ``LIFECYCLES`` / ``AUDIENCES``
/ ``PROVENANCES`` frozensets from ``mcp_server.shared.wiki_classification``
with an open-world registry. The set of values for each classification
axis is the union of:

    1. Python defaults declared in ``wiki_axis_defaults.py`` (bootstrap seed)
    2. User-added markdown files under ``wiki/_schema/<axis>/<value>.md``

Adding a new audience, lifecycle, kind, or provenance is done by writing
a markdown file with frontmatter — no Python edit required. Each value
ships its own regex detection patterns so the classifier composes the
4-tuple from pattern matches, not from hard-coded enum checks.

Schema file format::

    wiki/_schema/audiences/data-scientist.md
    ---
    name: data-scientist
    axis: audience
    display_name: Data scientist
    patterns:
      - '\\b(dataset|train(ing)?|inference|model|notebook|jupyter)\\b'
      - '\\b(scikit|pandas|numpy|pytorch|tensorflow)\\b'
    tag_aliases: [ds, ml, data]
    default: false
    ---

    # Data scientist audience

    Pages targeting practitioners building or analysing ML systems.

Unknown values fail validation; the error message proposes the closest
match via ``difflib.get_close_matches`` (user direction 2026-05-12:
"reject + suggest").

Module split (issue #134, coding-standards.md §4 — this file was 705
lines, over the 500-line hard limit): the default seed data for every
axis (kinds/lifecycles/audiences/provenances) now lives in
``wiki_axis_defaults.py``. This module keeps the ``AxisValue``/
``AxisRegistry`` data model, schema-file parsing, lookup helpers
(``match_axis``, ``did_you_mean``), and the reverse-DI wiki-root
provider (kept here because tests monkeypatch its module-level global
directly).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Final, Iterable

# ── Axis names ──────────────────────────────────────────────────────────

AXIS_KIND: Final[str] = "kind"
AXIS_LIFECYCLE: Final[str] = "lifecycle"
AXIS_AUDIENCE: Final[str] = "audience"
AXIS_PROVENANCE: Final[str] = "provenance"
AXES: Final[tuple[str, ...]] = (
    AXIS_KIND,
    AXIS_LIFECYCLE,
    AXIS_AUDIENCE,
    AXIS_PROVENANCE,
)

_SCHEMA_FOLDER: Final[str] = "_schema"


# ── Data model ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AxisValue:
    """One registered value for a classification axis.

    Fields:
        name: stable identifier (kebab-case, lowercase).
        axis: which axis this value belongs to (``kind`` / ``lifecycle`` / ...).
        display_name: human-readable label.
        patterns: compiled regex patterns; a content match contributes
            this value to the classification.
        tag_aliases: alternate names that may appear as memory tags;
            a tag match contributes this value to the classification.
        default: True if this is the default for new pages on this axis
            (e.g. ``seedling`` for lifecycle on non-ADR kinds).
        requires_generator: provenance-only — when True, a Classification
            whose ``provenance`` is this value must include a Generator
            block (model/version/prompt_template/generated_at).
        applies_to_kinds: lifecycle-only — restricts this value to a
            subset of kinds. Empty tuple = applies to all kinds.
        description: free-form documentation extracted from the page body.
    """

    name: str
    axis: str
    display_name: str = ""
    patterns: tuple[re.Pattern[str], ...] = ()
    tag_aliases: tuple[str, ...] = ()
    default: bool = False
    requires_generator: bool = False
    applies_to_kinds: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class AxisRegistry:
    """Indexed registry of axis values, loaded once per session.

    Lookup helpers preserve case-insensitive comparison on names and
    aliases. The registry is the source of truth for validation; the
    Python defaults below seed it on first load when the wiki has no
    ``_schema/`` folder.
    """

    by_axis: dict[str, dict[str, AxisValue]] = field(default_factory=dict)

    def values(self, axis: str) -> tuple[AxisValue, ...]:
        """All registered values for an axis."""
        return tuple(self.by_axis.get(axis, {}).values())

    def names(self, axis: str) -> frozenset[str]:
        """All registered value names for an axis."""
        return frozenset(self.by_axis.get(axis, {}).keys())

    def get(self, axis: str, name: str) -> AxisValue | None:
        """Look up a value by axis + name. Case-insensitive."""
        return self.by_axis.get(axis, {}).get(name.lower())

    def has(self, axis: str, name: str) -> bool:
        return self.get(axis, name) is not None

    def default_for(self, axis: str) -> AxisValue | None:
        """Return the value marked ``default: true`` for this axis, if any."""
        for v in self.by_axis.get(axis, {}).values():
            if v.default:
                return v
        return None


def _re(pattern: str) -> re.Pattern[str]:
    """Compile a regex with IGNORECASE — used when parsing user schema-file
    patterns (``_parse_axis_value_file``). Every axis pattern, default or
    user-supplied, is case-insensitive."""
    return re.compile(pattern, re.IGNORECASE)


# ── Registry construction ───────────────────────────────────────────────


def _empty_registry() -> AxisRegistry:
    return AxisRegistry(by_axis={axis: {} for axis in AXES})


def _ingest(registry: AxisRegistry, value: AxisValue) -> None:
    """Add a value to the registry, overriding any same-named entry."""
    bucket = registry.by_axis.setdefault(value.axis, {})
    bucket[value.name.lower()] = value


def build_default_registry() -> AxisRegistry:
    """Seed-only registry — no wiki file reads. Pure function.

    Imports ``wiki_axis_defaults`` lazily (function-local, not at module
    top) because that module imports ``AxisValue``/``AXIS_*`` back from
    this one to build its default seed data — a module-level import
    here would be circular.
    """
    from mcp_server.core.wiki_axis_defaults import ALL_DEFAULTS

    reg = _empty_registry()
    for v in ALL_DEFAULTS:
        _ingest(reg, v)
    return reg


_SCHEMA_FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(?P<fm>.*?)\n---\s*\n?", re.DOTALL)


def _parse_axis_value_file(rel_path: str, content: str) -> AxisValue | None:
    """Parse a single ``wiki/_schema/<axis>/<name>.md`` file.

    Returns the AxisValue or None on a malformed file. Never raises;
    schema files that fail to parse are skipped with a soft log line
    upstream.
    """
    m = _SCHEMA_FRONTMATTER_PATTERN.match(content)
    if not m:
        return None

    fm_text = m.group("fm")
    body = content[m.end() :].strip()
    fm: dict[str, object] = {}
    list_key: str | None = None
    list_items: list[str] = []
    for raw_line in fm_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if list_key is not None and line.startswith("  - "):
            list_items.append(line[4:].strip().strip("'\""))
            continue
        # End previous list if any
        if list_key is not None:
            fm[list_key] = list_items
            list_key = None
            list_items = []
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            value = value.strip()
            if value == "":
                list_key = key.strip()
                list_items = []
            else:
                fm[key.strip()] = value.strip().strip("'\"")
    if list_key is not None:
        fm[list_key] = list_items

    name = str(fm.get("name", "")).strip().lower()
    axis = str(fm.get("axis", "")).strip().lower()
    if not name or axis not in AXES:
        return None

    patterns_raw = fm.get("patterns", []) or []
    if not isinstance(patterns_raw, list):
        patterns_raw = []
    compiled: list[re.Pattern[str]] = []
    for p in patterns_raw:
        try:
            compiled.append(_re(str(p)))
        except re.error:
            continue

    tag_aliases_raw = fm.get("tag_aliases", []) or []
    if not isinstance(tag_aliases_raw, list):
        tag_aliases_raw = []

    applies_to_kinds_raw = fm.get("applies_to_kinds", []) or []
    if not isinstance(applies_to_kinds_raw, list):
        applies_to_kinds_raw = []

    return AxisValue(
        name=name,
        axis=axis,
        display_name=str(fm.get("display_name", "")).strip(),
        patterns=tuple(compiled),
        tag_aliases=tuple(str(t).lower() for t in tag_aliases_raw),
        default=_truthy(fm.get("default")),
        requires_generator=_truthy(fm.get("requires_generator")),
        applies_to_kinds=tuple(str(k).lower() for k in applies_to_kinds_raw),
        description=body,
    )


def _truthy(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"true", "yes", "1"}


def load_axis_registry(wiki_root: Path | str | None = None) -> AxisRegistry:
    """Build the registry: defaults + any user ``wiki/_schema/`` files.

    User files override defaults with the same name. Missing folders
    yield only the defaults. Never raises — malformed files are skipped.
    """
    registry = build_default_registry()
    if wiki_root is None:
        return registry

    root = Path(wiki_root).expanduser()
    schema_root = root / _SCHEMA_FOLDER
    if not schema_root.is_dir():
        return registry

    for axis_dir in schema_root.iterdir():
        if not axis_dir.is_dir():
            continue
        axis = axis_dir.name.lower()
        if axis not in AXES and axis not in {f"{a}s" for a in AXES}:
            continue
        for md in axis_dir.glob("*.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            parsed = _parse_axis_value_file(str(md), text)
            if parsed is not None:
                _ingest(registry, parsed)
    return registry


# ── Lookup helpers used by validators + classifier ──────────────────────


def did_you_mean(
    axis: str,
    unknown: str,
    registry: AxisRegistry,
    n: int = 3,
) -> tuple[str, ...]:
    """Suggest registered names close to ``unknown`` on the given axis.

    Implements the "reject + suggest" policy: validators raise
    ``ValueError`` with these suggestions in the error message.
    """
    candidates = list(registry.names(axis))
    suggestions = difflib.get_close_matches(
        unknown.lower(), [c.lower() for c in candidates], n=n, cutoff=0.4
    )
    return tuple(suggestions)


def match_axis(
    content: str,
    tags: Iterable[str] | None,
    axis: str,
    registry: AxisRegistry,
    *,
    restrict_to_kind: str | None = None,
) -> tuple[str, ...]:
    """Return value names whose patterns or tag aliases match the input.

    Order preserved as iteration order over registry values; first hit
    wins for axes that take a single value (kind, lifecycle, provenance).
    Caller is responsible for picking the head when single-valued.

    For lifecycle, ``restrict_to_kind`` filters out values whose
    ``applies_to_kinds`` is set and does not include the kind (so an
    ADR cannot be classified as ``seedling`` and a non-ADR cannot be
    ``proposed``).
    """
    matches: list[str] = []
    tag_set = {t.lower() for t in (tags or [])}
    for value in registry.values(axis):
        if (
            axis == AXIS_LIFECYCLE
            and value.applies_to_kinds
            and restrict_to_kind is not None
            and restrict_to_kind not in value.applies_to_kinds
        ):
            continue
        if (
            axis == AXIS_LIFECYCLE
            and not value.applies_to_kinds
            and restrict_to_kind == "adr"
        ):
            # Universal lifecycle values do not apply to ADRs (ADRs use
            # the proposed/accepted/rejected/superseded subset).
            continue
        if tag_set & set(value.tag_aliases):
            matches.append(value.name)
            continue
        for pat in value.patterns:
            if pat.search(content):
                matches.append(value.name)
                break
    return tuple(matches)


# ── Lazy singleton — cached for in-process classifier calls ─────────────
#
# Reverse DI (issue #126): core declares the *shape* of what it needs (a
# zero-arg callable returning the default wiki root) rather than importing
# ``infrastructure.config.WIKI_ROOT`` directly. The composition root
# (``mcp_server/__main__.py``) calls ``configure_default_wiki_root`` once
# at process boot with the real path; tests inject a fixture path the same
# way. No provider configured → ``get_registry()`` yields the seed-only
# defaults (still correct, just without user ``_schema/`` overrides).

_REGISTRY_CACHE: AxisRegistry | None = None
_WIKI_ROOT_PROVIDER: Callable[[], Path | str | None] | None = None


def configure_default_wiki_root(provider: Callable[[], Path | str | None]) -> None:
    """Composition-root injection point: register how to obtain the
    default wiki root used by the lazy ``get_registry()`` singleton.

    Call once at MCP server boot. Core never imports
    ``infrastructure.config`` directly — see issue #126.
    """
    global _WIKI_ROOT_PROVIDER
    _WIKI_ROOT_PROVIDER = provider


def get_registry() -> AxisRegistry:
    """Return the process-wide registry (defaults + wiki/_schema/ overrides).

    Cached after first call. Use ``reset_registry`` to force a reload —
    e.g. after the user edits a schema file and wants the change to
    take effect immediately.
    """
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        wiki_root = _WIKI_ROOT_PROVIDER() if _WIKI_ROOT_PROVIDER is not None else None
        _REGISTRY_CACHE = load_axis_registry(wiki_root)
    return _REGISTRY_CACHE


def reset_registry() -> None:
    """Force ``get_registry`` to re-read schema files on next call."""
    global _REGISTRY_CACHE
    _REGISTRY_CACHE = None
