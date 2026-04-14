"""Self-hosting wiki schema loader (Phase 1.3 of redesign).

The wiki describes its own schema. Kinds, classifier rules, views, and
triggers all live as markdown pages under reserved folders:

    wiki/_kinds/    — kind definitions (frontmatter: name, required_sections, ...)
    wiki/_rules/    — classifier rules (markdown tables: pattern → kind)
    wiki/_views/    — saved queries (fenced ``cortex-query`` blocks)
    wiki/_triggers/ — trigger declarations

This module is the READER — parses these files at MCP boot and returns
typed in-memory registries. Behaviour wires in Phase 2 / 5; for now the
loader is called once and its output is consumed by the gradually-migrating
classifier / synthesiser.

Pure core logic — reads via infrastructure/wiki_store.read_page, never
writes. Never raises; missing folders produce empty registries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp_server.core.wiki_pages import parse_page
from mcp_server.infrastructure.wiki_store import list_pages, read_page


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


def _parse_kind(rel_path: str, content: str) -> KindDefinition | None:
    doc = parse_page(content)
    fm = doc.frontmatter or {}
    name = fm.get("name") or Path(rel_path).stem
    if not name:
        return None
    return KindDefinition(
        name=str(name),
        display_name=str(fm.get("display_name", name)),
        dir_name=str(fm.get("dir_name", name + "s")),
        required_sections=[str(s) for s in fm.get("required_sections", []) or []],
        optional_sections=[str(s) for s in fm.get("optional_sections", []) or []],
        parent_kind=fm.get("parent_kind") or None,
        autofill_prompt=str(fm.get("autofill_prompt", "")),
    )


_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)


def _parse_rules_table(body: str) -> list[ClassifierRule]:
    """Extract rules from a markdown table.

    Expected columns (case-insensitive, order-flexible):
        pattern | kind | target | weight | note
    """
    rows = _TABLE_ROW_RE.findall(body)
    if len(rows) < 2:
        return []
    # First row is header
    header_cells = [c.strip().lower() for c in rows[0].split("|")]
    rules: list[ClassifierRule] = []
    for row in rows[2:]:  # skip header + separator
        cells = [c.strip() for c in row.split("|")]
        if len(cells) != len(header_cells):
            continue
        r = dict(zip(header_cells, cells))
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


def _parse_view(rel_path: str, content: str) -> ViewDefinition | None:
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


def _parse_trigger(rel_path: str, content: str) -> TriggerDefinition | None:
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


# ── Loader entry point ───────────────────────────────────────────────


def _load_folder(root: Path, folder: str, parser) -> dict:  # type: ignore[type-arg]
    """Read every .md under ``root/<folder>`` and apply parser.

    Returns dict keyed by parser output's ``name`` (or rel_path for views).
    """
    results: dict = {}
    full = root / folder
    if not full.exists():
        return results
    try:
        paths = list_pages(root, kind=None)
    except Exception:
        return results
    for rel in paths:
        # list_pages walks all PAGE_KINDS; filter to our reserved folder
        if not rel.startswith(folder + "/") and not rel.startswith(folder):
            continue
        content = read_page(root, rel)
        if content is None:
            continue
        try:
            parsed = parser(rel, content)
        except Exception:
            continue
        if parsed is None:
            continue
        key = getattr(parsed, "name", None) or rel
        results[key] = parsed
    return results


def _load_folder_direct(root: Path, folder: str, parser):
    """Alternative loader that globs directly — used for reserved folders
    like ``_kinds``, ``_rules`` which are not in PAGE_KINDS.
    """
    results: dict = {}
    full = root / folder
    if not full.exists():
        return results
    for p in sorted(full.rglob("*.md")):
        rel = str(p.relative_to(root)).replace("\\", "/")
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            parsed = parser(rel, content)
        except Exception:
            continue
        if parsed is None:
            continue
        key = getattr(parsed, "name", None) or rel
        results[key] = parsed
    return results


def load_registry(wiki_root: Path | str) -> WikiRegistry:
    """Read the self-hosting schema files and return the registry.

    Safe to call at MCP boot, after wiki_migrate, or on-demand. Missing
    folders yield empty sub-registries — no raises.
    """
    root = Path(wiki_root)
    kinds = _load_folder_direct(root, "_kinds", _parse_kind)

    # Rules live as a single markdown table per file; parse each and
    # concatenate preserving file order.
    rules: list[ClassifierRule] = []
    rules_dir = root / "_rules"
    if rules_dir.exists():
        for p in sorted(rules_dir.rglob("*.md")):
            try:
                content = p.read_text(encoding="utf-8")
                body = parse_page(content).body or ""
                rules.extend(_parse_rules_table(body))
            except Exception:
                continue

    views = _load_folder_direct(root, "_views", _parse_view)
    triggers = _load_folder_direct(root, "_triggers", _parse_trigger)
    return WikiRegistry(kinds=kinds, rules=rules, views=views, triggers=triggers)
