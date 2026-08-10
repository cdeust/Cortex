"""Wiki INDEX.md builder — pure, deterministic.

Groups wiki pages by domain then kind into a structured markdown index.
"""

from __future__ import annotations
from mcp_server.shared.wiki_layout import PAGE_KINDS


# source: structural — a wiki path is kind/filename (2 parts) or
# kind/domain/filename (3 parts); see the build_index docstring below.
_FLAT_PATH_PARTS = 2
_DOMAIN_SCOPED_PATH_PARTS = 3

_KIND_LABELS = {
    "adr": "Architecture Decisions",
    "specs": "Specifications",
    "guides": "Guides & How-To",
    "reference": "Reference",
    "conventions": "Conventions",
    "lessons": "Lessons Learned",
    "notes": "Notes",
    "journal": "Journal",
    "files": "File Documentation",
}


def _parse_page_entries(page_paths: list[str]) -> list[tuple[str, str, str, str]]:
    """Parse wiki-relative paths into ``(kind, domain, filename, full_path)``.

    Supports both flat (``notes/foo.md``) and domain-scoped
    (``notes/cortex/foo.md``) paths; non-matching paths are dropped.
    """
    entries: list[tuple[str, str, str, str]] = []
    for p in page_paths:
        parts = p.split("/")
        if len(parts) >= _FLAT_PATH_PARTS and parts[0] in PAGE_KINDS:
            kind = parts[0]
            filename = parts[-1].removesuffix(".md")
            domain = parts[1] if len(parts) >= _DOMAIN_SCOPED_PATH_PARTS else "_general"
            entries.append((kind, domain, filename, p))
    return entries


def _group_by_domain_kind(
    entries: list[tuple[str, str, str, str]],
) -> dict[str, dict[str, list[tuple[str, str]]]]:
    """Group parsed entries into ``{domain: {kind: [(filename, path), ...]}}``."""
    tree: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for kind, domain, filename, path in entries:
        tree.setdefault(domain, {}).setdefault(kind, []).append((filename, path))
    return tree


def _render_domain_section(
    domain: str, kinds: dict[str, list[tuple[str, str]]]
) -> list[str]:
    """Render one domain's ``## <label> (N pages)`` section, grouped by kind."""
    page_count = sum(len(pages) for pages in kinds.values())
    label = "Global" if domain == "_general" else domain.replace("-", " ").title()
    lines = [f"## {label} ({page_count} pages)", ""]
    for kind in PAGE_KINDS:
        pages = kinds.get(kind, [])
        if not pages:
            continue
        kind_label = _KIND_LABELS.get(kind, kind.title())
        lines.append(f"### {kind_label}")
        lines.append("")
        for filename, path in sorted(pages):
            lines.append(f"- [{filename}]({path})")
        lines.append("")
    return lines


def build_index(page_paths: list[str]) -> str:
    """Build a structured INDEX.md grouped by domain then kind.

    Each path is relative to the wiki root. Pure function — no I/O. See
    ``_parse_page_entries``/``_group_by_domain_kind``/``_render_domain_section``
    for the three-step pipeline this composes.
    """
    entries = _parse_page_entries(page_paths)
    total = len(entries)
    domains = sorted({e[1] for e in entries})
    domain_count = len([d for d in domains if d != "_general"])
    tree = _group_by_domain_kind(entries)

    lines = [
        "# Cortex Knowledge Base",
        "",
        f"**{total} pages** across {domain_count} domains",
        "",
    ]
    for domain in sorted(tree.keys(), key=lambda d: "zzz" if d == "_general" else d):
        lines.extend(_render_domain_section(domain, tree[domain]))
    return "\n".join(lines)
