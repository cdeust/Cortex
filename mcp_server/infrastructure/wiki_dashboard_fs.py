"""Filesystem boundary for core/wiki_coverage_dashboard.py (issue #560:
core/ may not import os/pathlib or perform I/O). Wired in via
core.wiki_coverage_dashboard.configure_dashboard_filesystem —
mcp_server/__main__.py for production, tests_py/conftest.py for the test
session.

source: ADR-0298 (issue #560)
"""

from __future__ import annotations

from pathlib import Path


def count_curation_gaps_under(domain_dir: str) -> tuple[int, int]:
    """Walk a domain's pages and return ``(total_pages, total_open_gaps)``.

    source: ADR-0298"""
    path = Path(domain_dir)
    if not path.is_dir():
        return 0, 0
    total = 0
    gaps = 0
    for md in path.rglob("*.md"):
        total += 1
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end < 0:
            continue
        block = text[3:end]
        in_list = False
        for line in block.splitlines():
            if line.startswith("curation_gaps:"):
                in_list = True
                continue
            if in_list:
                if line.startswith((" ", "\t")) and line.lstrip().startswith("- "):
                    gaps += 1
                else:
                    in_list = False
    return total, gaps


def kind_page_counts(wiki_root: str, domain: str) -> dict[str, int]:
    """Count pages per kind directory for a domain.

    source: ADR-0298"""
    root = Path(wiki_root)
    counts: dict[str, int] = {}
    for kind_dir in root.iterdir():
        if not kind_dir.is_dir() or kind_dir.name.startswith((".", "_")):
            continue
        target = kind_dir / domain
        if not target.is_dir():
            continue
        counts[kind_dir.name] = sum(1 for p in target.rglob("*.md") if p.is_file())
    return counts


def domain_dirs_under(wiki_root: str, domain: str) -> list[str]:
    """Every ``<kind>/<domain>`` directory under ``wiki_root`` that exists,
    skipping dot/underscore kind buckets (e.g. ``_dashboards``).

    source: ADR-0298"""
    root = Path(wiki_root)
    return [
        str(kd / domain)
        for kd in root.iterdir()
        if kd.is_dir() and not kd.name.startswith((".", "_"))
    ]


def wiki_root_is_dir(wiki_root: str) -> bool:
    return Path(wiki_root).is_dir()


def write_dashboard_pages(wiki_root: str, pages: dict[str, str]) -> dict[str, str]:
    """Write one dashboard file per (domain -> markdown) pair under
    ``wiki_root/_dashboards/``, plus an index page. Returns the map of
    domain -> written path for the pages actually written (a page whose
    write fails is dropped, not fatal).

    source: ADR-0298"""
    target_dir = Path(wiki_root) / "_dashboards"
    target_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for domain, page in pages.items():
        path = target_dir / f"{domain}.md"
        try:
            path.write_text(page, encoding="utf-8")
            out[domain] = str(path)
        except OSError:
            continue
    index = [
        "---",
        "title: Coverage dashboards",
        "kind: reference",
        "scope: coverage-index",
        "provenance: auto-generated",
        "---",
        "",
        "# Coverage dashboards",
        "",
        "_One page per project, regenerated on every consolidate cycle._",
        "",
        "| Project | Dashboard |",
        "|---|---|",
    ]
    for d in sorted(out.keys()):
        index.append(f"| {d} | [`_dashboards/{d}.md`](_dashboards/{d}.md) |")
    try:
        (target_dir / "_index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    except OSError:
        pass
    return out
