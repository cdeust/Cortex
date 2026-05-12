"""Wiki axis registry — data-driven classification with extensible values.

User direction (2026-05-12): "having only 4 values for each is a band-aid
fix, we should be able to manage anything using regex and recognition."

This module replaces the hardcoded ``KINDS`` / ``LIFECYCLES`` / ``AUDIENCES``
/ ``PROVENANCES`` frozensets from ``mcp_server.shared.wiki_classification``
with an open-world registry. The set of values for each classification
axis is the union of:

    1. Python defaults declared in this module (bootstrap seed)
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
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterable

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


# ── Default seed (bootstrap when wiki has no _schema/) ──────────────────


def _re(pattern: str) -> re.Pattern[str]:
    """Compile a regex with IGNORECASE — every axis pattern is case-insensitive."""
    return re.compile(pattern, re.IGNORECASE)


# Each tuple = (name, display_name, patterns, tag_aliases, kwargs).
_DEFAULT_KINDS: tuple[AxisValue, ...] = (
    AxisValue(
        name="adr",
        axis=AXIS_KIND,
        display_name="ADR (Architecture Decision Record)",
        patterns=(
            _re(r"\b(decided to|decision:|the decision is|chose .+ because)\b"),
            _re(r"\b(rejected .+ (due to|because)|we will use|selected .+ over)\b"),
        ),
        tag_aliases=("decision", "adr", "architecture"),
        description="Nygard/MADR-style record of a single architectural decision.",
    ),
    AxisValue(
        name="tutorial",
        axis=AXIS_KIND,
        display_name="Tutorial",
        patterns=(
            _re(
                r"\b(tutorial:|in this tutorial|we['']?ll (learn|build|create|walk through))\b"
            ),
            _re(r"\b(by the end of this tutorial|getting started:|step 1[:.])\b"),
        ),
        tag_aliases=("tutorial", "getting-started"),
        description="Learn-by-doing walkthrough (Diátaxis).",
    ),
    AxisValue(
        name="how-to",
        axis=AXIS_KIND,
        display_name="How-to guide",
        patterns=(_re(r"\b(how to |how do (you|i) |here['']?s how to )\b"),),
        tag_aliases=("how-to", "howto", "guide"),
        description="Task-oriented recipe for a known goal (Diátaxis / DITA task).",
    ),
    AxisValue(
        name="reference",
        axis=AXIS_KIND,
        display_name="Reference",
        patterns=(),  # reference is usually identified by tags / producer, not content
        tag_aliases=("reference", "api", "spec", "code-reference"),
        description="Authoritative lookup table — API docs, file docs, schema refs.",
    ),
    AxisValue(
        name="explanation",
        axis=AXIS_KIND,
        display_name="Explanation",
        patterns=(
            _re(r"\b(what is|why does|the reason|conceptually|under the hood)\b"),
            # Lesson-shaped content collapses into explanation per ADR-2244 §4.1.
            _re(r"\b(the bug was|root cause|lesson learned|fix:|fixed by)\b"),
            # Convention-shaped content also collapses into explanation.
            _re(r"\b(always use|never |the canonical|convention:|rule:|standard:)\b"),
        ),
        tag_aliases=(
            "explanation",
            "concept",
            "lesson",
            "convention",
            "rule",
            "standard",
        ),
        description="Concept-oriented prose explaining the 'why' (Diátaxis).",
    ),
    AxisValue(
        name="runbook",
        axis=AXIS_KIND,
        display_name="Runbook",
        patterns=(
            _re(r"\b(runbook|incident response|on[- ]call|when (the )?alert fires)\b"),
            _re(r"\b(if (this|that) happens|recovery procedure|rollback steps?)\b"),
        ),
        tag_aliases=("runbook", "playbook", "incident", "oncall"),
        description="SRE incident-response procedure (Rootly/Squadcast convention).",
    ),
    AxisValue(
        name="rfc",
        axis=AXIS_KIND,
        display_name="RFC (Request For Comments)",
        patterns=(
            _re(
                r"\b(rfc:|proposal:|we propose to|proposed (design|change|approach))\b"
            ),
            _re(r"\b(this rfc|request for comments)\b"),
        ),
        tag_aliases=("rfc", "proposal", "spec", "design"),
        description="Pre-decision design proposal open for comment (IETF/arc42 §4).",
    ),
    AxisValue(
        name="journal",
        axis=AXIS_KIND,
        display_name="Journal entry",
        patterns=(
            _re(r"^##?\s*\d{4}-\d{2}-\d{2}\b"),  # dated H1/H2 header
        ),
        tag_aliases=("journal", "diary", "log"),
        description="Dated reflective entry — digital-garden / Confluence blog style.",
    ),
)


_DEFAULT_LIFECYCLES: tuple[AxisValue, ...] = (
    AxisValue(
        name="seedling",
        axis=AXIS_LIFECYCLE,
        display_name="Seedling",
        default=True,  # default for new non-ADR pages
        patterns=(_re(r"_to be (filled|written)_"),),
        tag_aliases=("seedling", "seed", "new", "stub"),
        description="Initial stub, expected to grow (digital-garden convention).",
    ),
    AxisValue(
        name="draft",
        axis=AXIS_LIFECYCLE,
        display_name="Draft",
        patterns=(_re(r"\bdraft\b"),),
        tag_aliases=("draft", "wip"),
        description="Work in progress, not yet published.",
    ),
    AxisValue(
        name="active",
        axis=AXIS_LIFECYCLE,
        display_name="Active",
        patterns=(),
        tag_aliases=("active", "current", "live"),
        description="Maintained and authoritative.",
    ),
    AxisValue(
        name="deprecated",
        axis=AXIS_LIFECYCLE,
        display_name="Deprecated",
        patterns=(_re(r"\bdeprecated\b"),),
        tag_aliases=("deprecated", "legacy"),
        description="Still readable, but new use should prefer the replacement.",
    ),
    AxisValue(
        name="archived",
        axis=AXIS_LIFECYCLE,
        display_name="Archived",
        patterns=(_re(r"\barchived\b"),),
        tag_aliases=("archived", "historic"),
        description="Frozen historical record; do not modify.",
    ),
    # ADR-specific lifecycle subset (Nygard / MADR).
    AxisValue(
        name="proposed",
        axis=AXIS_LIFECYCLE,
        display_name="Proposed (ADR)",
        default=True,  # default for new ADRs
        applies_to_kinds=("adr",),
        patterns=(_re(r"\bproposed\b"),),
        tag_aliases=("proposed",),
        description="ADR awaiting decision (Nygard).",
    ),
    AxisValue(
        name="accepted",
        axis=AXIS_LIFECYCLE,
        display_name="Accepted (ADR)",
        applies_to_kinds=("adr",),
        patterns=(_re(r"\baccepted\b"),),
        tag_aliases=("accepted",),
        description="ADR adopted and in effect (Nygard).",
    ),
    AxisValue(
        name="rejected",
        axis=AXIS_LIFECYCLE,
        display_name="Rejected (ADR)",
        applies_to_kinds=("adr",),
        patterns=(_re(r"\brejected\b"),),
        tag_aliases=("rejected",),
        description="ADR considered and dismissed (Nygard).",
    ),
    AxisValue(
        name="superseded",
        axis=AXIS_LIFECYCLE,
        display_name="Superseded (ADR)",
        applies_to_kinds=("adr",),
        patterns=(_re(r"\bsuperseded\b"),),
        tag_aliases=("superseded",),
        description="ADR replaced by a later one (Nygard).",
    ),
)


_DEFAULT_AUDIENCES: tuple[AxisValue, ...] = (
    AxisValue(
        name="developer",
        axis=AXIS_AUDIENCE,
        display_name="Developer",
        default=True,
        patterns=(
            _re(r"\b(function|class|method|import|module|API|SDK|library|interface)\b"),
        ),
        tag_aliases=("dev", "developer", "engineer", "code"),
        description="Software engineers writing or modifying code.",
    ),
    AxisValue(
        name="ops",
        axis=AXIS_AUDIENCE,
        display_name="Operations / SRE",
        patterns=(
            _re(
                r"\b(deploy(ment)?|kubernetes|terraform|infra(structure)?|cluster|node|pod)\b"
            ),
            _re(r"\b(sre|on[- ]call|incident|alert|monitoring|observability)\b"),
        ),
        tag_aliases=("ops", "sre", "infra", "deploy", "k8s"),
        description="Operators of production systems.",
    ),
    AxisValue(
        name="security",
        axis=AXIS_AUDIENCE,
        display_name="Security",
        patterns=(
            _re(
                r"\b(auth(entication|orization)?|crypto(graphy)?|vulnerab(le|ility)|cve|threat model)\b"
            ),
            _re(r"\b(secret|token|credential|session|sso|oauth|tls|encryption)\b"),
        ),
        tag_aliases=("security", "auth", "crypto", "vulnerability", "secops"),
        description="Security engineers and reviewers.",
    ),
    AxisValue(
        name="internal",
        axis=AXIS_AUDIENCE,
        display_name="Internal",
        patterns=(),
        tag_aliases=("internal", "private"),
        description="Internal team-only content (not for external publication).",
    ),
    AxisValue(
        name="external",
        axis=AXIS_AUDIENCE,
        display_name="External",
        patterns=(),
        tag_aliases=("external", "public", "customer"),
        description="External-facing documentation for users / customers.",
    ),
)


_DEFAULT_PROVENANCES: tuple[AxisValue, ...] = (
    AxisValue(
        name="human",
        axis=AXIS_PROVENANCE,
        display_name="Human-authored",
        default=True,
        patterns=(),
        tag_aliases=("human", "authored"),
        description="Hand-written by a person.",
    ),
    AxisValue(
        name="ai-generated",
        axis=AXIS_PROVENANCE,
        display_name="AI-generated",
        patterns=(),
        tag_aliases=("ai-generated", "synthesized", "synth"),
        requires_generator=True,
        description="Produced by an LLM via a template prompt.",
    ),
    AxisValue(
        name="imported",
        axis=AXIS_PROVENANCE,
        display_name="Imported",
        patterns=(),
        tag_aliases=("imported", "import"),
        description="Bulk-imported from an external memory system.",
    ),
    AxisValue(
        name="auto-generated",
        axis=AXIS_PROVENANCE,
        display_name="Auto-generated (codebase)",
        patterns=(),
        tag_aliases=("auto-generated", "code-reference", "codebase"),
        requires_generator=True,
        description="Produced by ``codebase_analyze`` / ``wiki_seed_codebase``.",
    ),
)


_ALL_DEFAULTS: tuple[AxisValue, ...] = (
    _DEFAULT_KINDS + _DEFAULT_LIFECYCLES + _DEFAULT_AUDIENCES + _DEFAULT_PROVENANCES
)


# ── Registry construction ───────────────────────────────────────────────


def _empty_registry() -> AxisRegistry:
    return AxisRegistry(by_axis={axis: {} for axis in AXES})


def _ingest(registry: AxisRegistry, value: AxisValue) -> None:
    """Add a value to the registry, overriding any same-named entry."""
    bucket = registry.by_axis.setdefault(value.axis, {})
    bucket[value.name.lower()] = value


def build_default_registry() -> AxisRegistry:
    """Seed-only registry — no wiki file reads. Pure function."""
    reg = _empty_registry()
    for v in _ALL_DEFAULTS:
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


_REGISTRY_CACHE: AxisRegistry | None = None


def get_registry() -> AxisRegistry:
    """Return the process-wide registry (defaults + wiki/_schema/ overrides).

    Cached after first call. Use ``reset_registry`` to force a reload —
    e.g. after the user edits a schema file and wants the change to
    take effect immediately.
    """
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        from mcp_server.infrastructure.config import WIKI_ROOT

        _REGISTRY_CACHE = load_axis_registry(WIKI_ROOT)
    return _REGISTRY_CACHE


def reset_registry() -> None:
    """Force ``get_registry`` to re-read schema files on next call."""
    global _REGISTRY_CACHE
    _REGISTRY_CACHE = None
