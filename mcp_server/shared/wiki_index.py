"""Wiki INDEX.md builder — pure, deterministic.

Groups wiki pages by domain then kind into a structured markdown index.
"""

from __future__ import annotations
from mcp_server.shared.wiki_layout import PAGE_KINDS


# source: structural — a wiki path is kind/filename (2 parts) or
# kind/domain/filename (3 parts); see the build_index docstring below.
_FLAT_PATH_PARTS = 2
_DOMAIN_SCOPED_PATH_PARTS = 3


def build_index(page_paths: list[str]) -> str:
    """Build a structured INDEX.md grouped by domain then kind.

    Each path is relative to the wiki root. Supports both flat
    (``notes/foo.md``) and domain-scoped (``notes/cortex/foo.md``) paths.
    Pure function — no I/O.
    """

    # Parse paths into (kind, domain, filename, full_path)
    entries: list[tuple[str, str, str, str]] = []
    for p in page_paths:
        parts = p.split("/")
        if len(parts) >= _FLAT_PATH_PARTS and parts[0] in PAGE_KINDS:
            kind = parts[0]
            if len(parts) >= _DOMAIN_SCOPED_PATH_PARTS:
                domain = parts[1]
                filename = parts[-1].removesuffix(".md")
            else:
                domain = "_general"
                filename = parts[-1].removesuffix(".md")
            entries.append((kind, domain, filename, p))

    total = len(entries)
    domains = sorted({e[1] for e in entries})
    domain_count = len([d for d in domains if d != "_general"])

    # Group by domain → kind → pages
    tree: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for kind, domain, filename, path in entries:
        tree.setdefault(domain, {}).setdefault(kind, []).append((filename, path))

    _kind_labels = {
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

    lines = [
        "# Cortex Knowledge Base",
        "",
        f"**{total} pages** across {domain_count} domains",
        "",
    ]

    # Render each domain
    for domain in sorted(tree.keys(), key=lambda d: "zzz" if d == "_general" else d):
        kinds = tree[domain]
        page_count = sum(len(pages) for pages in kinds.values())
        label = "Global" if domain == "_general" else domain.replace("-", " ").title()
        lines.append(f"## {label} ({page_count} pages)")
        lines.append("")

        for kind in PAGE_KINDS:
            pages = kinds.get(kind, [])
            if not pages:
                continue
            kind_label = _kind_labels.get(kind, kind.title())
            lines.append(f"### {kind_label}")
            lines.append("")
            for filename, path in sorted(pages):
                lines.append(f"- [{filename}]({path})")
            lines.append("")

    return "\n".join(lines)
