"""Wiki axis registry — data-driven classification with extensible values.

source: ADR-0292"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
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



# ── Data model ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AxisValue:
    """One registered value for a classification axis.

    source: ADR-0292"""

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


def axis_registry_values(registry: "AxisRegistry", axis: str) -> tuple[AxisValue, ...]:
    """All registered values for an axis.

    source: ADR-0292"""
    return tuple(registry.by_axis.get(axis, {}).values())


def axis_registry_names(registry: "AxisRegistry", axis: str) -> frozenset[str]:
    """All registered value names for an axis."""
    return frozenset(registry.by_axis.get(axis, {}).keys())


def axis_registry_get(
    registry: "AxisRegistry", axis: str, name: str
) -> AxisValue | None:
    """Look up a value by axis + name. Case-insensitive."""
    return registry.by_axis.get(axis, {}).get(name.lower())


def axis_registry_has(registry: "AxisRegistry", axis: str, name: str) -> bool:
    return axis_registry_get(registry, axis, name) is not None


def axis_registry_default_for(registry: "AxisRegistry", axis: str) -> AxisValue | None:
    """Return the value marked ``default: true`` for this axis, if any."""
    for v in registry.by_axis.get(axis, {}).values():
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

    source: ADR-0292"""
    from mcp_server.core.wiki_axis_defaults import ALL_DEFAULTS  # noqa: PLC0415 — source: ADR-0292

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
        # source: ADR-0292
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


def load_axis_registry(wiki_root: str | None = None) -> AxisRegistry:
    """Build the registry: defaults + any user ``wiki/_schema/`` files.

    User files override defaults with the same name. Missing folders
    yield only the defaults. Never raises — malformed files are skipped.
    """
    if _SCHEMA_FILE_READER is None:
        raise RuntimeError(
            "wiki_axis_registry schema_file_reader not configured — call "
            "configure_schema_file_reader() at the composition root first"
        )
    registry = build_default_registry()
    for axis_dir_name, file_path, text in _SCHEMA_FILE_READER(wiki_root):
        axis = axis_dir_name.lower()
        if axis not in AXES and axis not in {f"{a}s" for a in AXES}:
            continue
        parsed = _parse_axis_value_file(file_path, text)
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
    candidates = list(axis_registry_names(registry, axis))
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

    source: ADR-0292"""
    matches: list[str] = []
    tag_set = {t.lower() for t in (tags or [])}
    for value in axis_registry_values(registry, axis):
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
            # source: ADR-0292

            continue
        if tag_set & set(value.tag_aliases):
            matches.append(value.name)
            continue
        for pat in value.patterns:
            if pat.search(content):
                matches.append(value.name)
                break
    return tuple(matches)


# source: ADR-0292


_REGISTRY_CACHE: AxisRegistry | None = None
_WIKI_ROOT_PROVIDER: Callable[[], "str | None"] | None = None

# Composition-root injection seam for the _schema/ file reads (core may
# not import os/pathlib or perform I/O; issue #560). Real implementation
# lives in mcp_server/infrastructure/wiki_axis_fs.py, wired once via
# configure_schema_file_reader.
SchemaFileReader = Callable[["str | None"], "list[tuple[str, str, str]]"]
_SCHEMA_FILE_READER: SchemaFileReader | None = None


def configure_default_wiki_root(provider: Callable[[], "str | None"]) -> None:
    """Composition-root injection point: register how to obtain the
    default wiki root used by the lazy ``get_registry()`` singleton.

    source: ADR-0292"""
    global _WIKI_ROOT_PROVIDER
    _WIKI_ROOT_PROVIDER = provider


def configure_schema_file_reader(reader: SchemaFileReader) -> None:
    """Composition-root hook: register the real ``_schema/`` file reader.

    source: ADR-0292 (issue #560)"""
    global _SCHEMA_FILE_READER
    _SCHEMA_FILE_READER = reader


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
