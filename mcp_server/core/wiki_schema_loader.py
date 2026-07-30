"""Self-hosting wiki schema — data model + pure parsers (Phase 1.3 of redesign).

The wiki describes its own schema. Kinds, classifier rules, views, and
triggers all live as markdown pages under reserved folders:

    wiki/_kinds/    — kind definitions (frontmatter: name, required_sections, ...)
    wiki/_rules/    — classifier rules (markdown tables: pattern → kind)
    wiki/_views/    — saved queries (fenced ``cortex-query`` blocks)
    wiki/_triggers/ — trigger declarations

This module declares the typed registries and the pure ``str -> dataclass``
parsers for each file shape. It performs zero I/O — every parser here takes
already-read file content as a plain string.

Port-and-adapter split (issue #126): the previous single-file version of
this module also walked the filesystem (via ``infrastructure.wiki_store``)
to actually build a registry from a wiki root. That I/O orchestration now
lives in ``mcp_server.infrastructure.wiki_schema_reader.load_registry`` —
the adapter that reads files on disk and calls the parsers declared here.
Composition roots (handlers, ``mcp_server/__main__.py``) import
``load_registry`` from that infrastructure module, not from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp_server.core.wiki_pages import parse_page


# ── Registry dataclasses ──────────────────────────────────────────────


@dataclass(frozen=True)
class KindDefinition:
    """A user-declared page kind, parsed from wiki/_kinds/<name>.md.

    Frontmatter schema:
      name: str                    — the kind identifier (e.g. "adr")
      display_name: str            — human-readable label
      dir_name: str                — directory under wiki/ for this kind
      required_sections: list[str] — H2 headings that must be present
      optional_sections: list[str] — H2 headings that may be present
      parent_kind: str | null      — inheritance (e.g. "experiment" extends "note")
      autofill_prompt: str         — LLM prompt template for synthesis
    """

    name: str
    display_name: str
    dir_name: str
    required_sections: list[str] = field(default_factory=list)
    optional_sections: list[str] = field(default_factory=list)
    parent_kind: str | None = None
    autofill_prompt: str = ""


@dataclass(frozen=True)
class ClassifierRule:
    """A single classifier rule parsed from a wiki/_rules/*.md table row.

    Each rule is a pattern + target kind + weight. Rules are evaluated
    in order; first match wins.
    """

    pattern: str
    pattern_kind: str  # 'prefix' | 'regex' | 'substring' | 'tag'
    target_kind: str | None  # None → reject
    weight: float = 1.0
    note: str = ""


@dataclass(frozen=True)
class ViewDefinition:
    """A saved query page. The fenced ``cortex-query`` block is the body."""

    name: str
    rel_path: str
    query: str
    description: str = ""


@dataclass(frozen=True)
class TriggerDefinition:
    """A trigger declaration from wiki/_triggers/*.md."""

    name: str
    event: str  # 'session_end' | 'memory_stored' | 'benchmark_run' | ...
    condition: str
    action: str


@dataclass(frozen=True)
class WikiRegistry:
    """Aggregate output of the loader."""

    kinds: dict[str, KindDefinition]
    rules: list[ClassifierRule]
    views: dict[str, ViewDefinition]
    triggers: dict[str, TriggerDefinition]

    @property
    def known_kind_names(self) -> set[str]:
        return set(self.kinds.keys())


# ── Parsers ───────────────────────────────────────────────────────────


def parse_kind(rel_path: str, content: str) -> KindDefinition | None:
    doc = parse_page(content)
    fm = doc.frontmatter or {}
    name = str(fm.get("name") or Path(rel_path).stem)
    if not name:
        return None
    required = fm.get("required_sections")
    optional = fm.get("optional_sections")
    parent = fm.get("parent_kind")
    return KindDefinition(
        name=name,
        display_name=str(fm.get("display_name", name)),
        dir_name=str(fm.get("dir_name", f"{name}s")),
        required_sections=(
            [str(s) for s in required] if isinstance(required, list) else []
        ),
        optional_sections=(
            [str(s) for s in optional] if isinstance(optional, list) else []
        ),
        parent_kind=str(parent) if parent else None,
        autofill_prompt=str(fm.get("autofill_prompt", "")),
    )


_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)


# source: structural — a markdown table needs a header row plus a separator
# row before any rule row can exist (see the row indexing below).
_MIN_TABLE_ROWS = 2


def parse_rules_table(body: str) -> list[ClassifierRule]:
    """Extract rules from a markdown table.

    Expected columns (case-insensitive, order-flexible):
        pattern | kind | target | weight | note
    """
    rows = _TABLE_ROW_RE.findall(body)
    if len(rows) < _MIN_TABLE_ROWS:
        return []
    # First row is header
    header_cells = [c.strip().lower() for c in rows[0].split("|")]
    rules: list[ClassifierRule] = []
    for row in rows[2:]:  # skip header + separator
        cells = [c.strip() for c in row.split("|")]
        if len(cells) != len(header_cells):
            continue
        # strict=True: the length check immediately above already guarantees
        # equal lengths here.
        r = dict(zip(header_cells, cells, strict=True))
        if not r.get("pattern") or not r.get("kind"):
            continue
        target = r.get("target") or None
        if target == "reject" or target == "-" or target == "":
            target = None
        try:
            weight = float(r.get("weight", "1.0"))
        except ValueError:
            weight = 1.0
        rules.append(
            ClassifierRule(
                pattern=r["pattern"],
                pattern_kind=r["kind"],
                target_kind=target,
                weight=weight,
                note=r.get("note", ""),
            )
        )
    return rules


_QUERY_BLOCK_RE = re.compile(r"```cortex-query\n(.*?)\n```", re.DOTALL)


def parse_view(rel_path: str, content: str) -> ViewDefinition | None:
    doc = parse_page(content)
    fm = doc.frontmatter or {}
    m = _QUERY_BLOCK_RE.search(doc.body or "")
    if not m:
        return None
    return ViewDefinition(
        name=str(fm.get("name") or Path(rel_path).stem),
        rel_path=rel_path,
        query=m.group(1).strip(),
        description=str(fm.get("description", "")),
    )


def parse_trigger(rel_path: str, content: str) -> TriggerDefinition | None:
    doc = parse_page(content)
    fm = doc.frontmatter or {}
    event = fm.get("event")
    if not event:
        return None
    return TriggerDefinition(
        name=str(fm.get("name") or Path(rel_path).stem),
        event=str(event),
        condition=str(fm.get("condition", "")),
        action=str(fm.get("action", "")),
    )


# The filesystem walk that builds a ``WikiRegistry`` from a wiki root is
# I/O and lives in ``mcp_server.infrastructure.wiki_schema_reader.load_registry``
# (issue #126) — it imports the dataclasses and parsers above and drives
# them from files read via ``Path`` / ``infrastructure.wiki_store``.
