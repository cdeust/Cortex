"""Self-hosting wiki schema reader — I/O half of the schema loader.

Port-and-adapter split (issue #126): ``mcp_server.core.wiki_schema_loader``
declares the pure data model (``KindDefinition``, ``ClassifierRule``,
``ViewDefinition``, ``TriggerDefinition``, ``WikiRegistry``) and the pure
string-to-dataclass parsers. This module is the adapter — it walks the
wiki root on disk (``Path.rglob`` + ``read_text``) and feeds file content
through those core parsers to build a ``WikiRegistry``.

Composition roots (``mcp_server/__main__.py``, and the wiki_curate /
wiki_synthesize / wiki_refine / wiki_view handlers) call ``load_registry``
directly with an explicit ``wiki_root`` — this module performs real I/O
and must never be imported from ``core/``.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.core.wiki_pages import parse_page
from mcp_server.core.wiki_schema_loader import (
    ClassifierRule,
    WikiRegistry,
    parse_kind,
    parse_rules_table,
    parse_trigger,
    parse_view,
)
from mcp_server.observability import silent_failure


def _load_folder_direct(root: Path, folder: str, parser):
    """Glob every ``.md`` under ``root/<folder>`` and apply ``parser``.

    Used for reserved folders (``_kinds``, ``_rules``, ``_views``,
    ``_triggers``) that are not part of ``PAGE_KINDS``, so they are walked
    directly via ``rglob`` rather than through ``wiki_store.list_pages``.
    Never raises; a folder that doesn't exist yields an empty dict, and a
    file that fails to parse is skipped.
    """
    results: dict = {}
    full = root / folder
    if not full.exists():
        return results
    for p in sorted(full.rglob("*.md")):
        rel = str(p.relative_to(root)).replace("\\", "/")
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            parsed = parser(rel, content)
        except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
            silent_failure.note("wiki_schema_reader.page_parse", exc)
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
    kinds = _load_folder_direct(root, "_kinds", parse_kind)

    # Rules live as a single markdown table per file; parse each and
    # concatenate preserving file order.
    rules: list[ClassifierRule] = []
    rules_dir = root / "_rules"
    if rules_dir.exists():
        for p in sorted(rules_dir.rglob("*.md")):
            try:
                content = p.read_text(encoding="utf-8")
                body = parse_page(content).body or ""
                rules.extend(parse_rules_table(body))
            except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
                silent_failure.note("wiki_schema_reader.rules_parse", exc)
                continue

    views = _load_folder_direct(root, "_views", parse_view)
    triggers = _load_folder_direct(root, "_triggers", parse_trigger)
    return WikiRegistry(kinds=kinds, rules=rules, views=views, triggers=triggers)


__all__ = ["load_registry"]
