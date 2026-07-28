"""Per-project coverage dashboard.

Meadows leverage-point audit 2026-05-18 identified Level 6 (information
flows) as a top-3 intervention: the system knows what's missing
(``curation_gaps`` per page, scope audit per project) but the user
doesn't unless they drill into 700 individual file-docs. The
dashboard surfaces the gap report as a single readable page per
project so the user (and the headless authoring worker) sees at a
glance what's covered, what's empty, and what's in progress.

The dashboard for each project lives at::

    wiki/_dashboards/<domain>.md

Generated content — NOT human-authored. Regenerated on every
``consolidate`` cycle so it stays current.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mcp_server.core.wiki_coverage import (
    audit_domain,
    audit_files,
)
from mcp_server.observability import silent_failure
from mcp_server.shared.domain_mapping import _build_registry


@dataclass(frozen=True)
class SlotStatus:
    """One slot's fill status for a project."""

    scope_name: str
    title: str
    description: str
    covered: bool
    anchor_path: str | None
    suggested_path: str
    pages_count: int


def _scope_slot_statuses(wiki_root: str, domain: str) -> list[SlotStatus]:
    """Convert a domain's ``DomainCoverage`` into typed slot statuses."""
    cov = audit_domain(wiki_root, domain)
    out: list[SlotStatus] = []
    for sc in cov.scopes:
        out.append(
            SlotStatus(
                scope_name=sc.scope.name,
                title=sc.scope.title,
                description=sc.scope.description,
                covered=sc.covered,
                anchor_path=sc.anchor_page,
                suggested_path=sc.suggested_path,
                pages_count=sc.page_count,
            )
        )
    return out


def _count_curation_gaps_under(domain_dir: Path) -> tuple[int, int]:
    """Walk a domain's pages and return ``(total_pages, total_open_gaps)``.

    Open gaps come from each page's frontmatter ``curation_gaps``
    list — produced by the file-doc skeleton generator. This is the
    actuator-facing metric: how much work is queued.
    """
    if not domain_dir.is_dir():
        return 0, 0
    total = 0
    gaps = 0
    for md in domain_dir.rglob("*.md"):
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


def _kind_page_counts(wiki_root: Path, domain: str) -> dict[str, int]:
    """Count pages per kind directory for a domain."""
    counts: dict[str, int] = {}
    for kind_dir in wiki_root.iterdir():
        if not kind_dir.is_dir() or kind_dir.name.startswith((".", "_")):
            continue
        target = kind_dir / domain
        if not target.is_dir():
            continue
        counts[kind_dir.name] = sum(1 for p in target.rglob("*.md") if p.is_file())
    return counts


# How many uncovered source files the dashboard lists before truncating.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_UNCOVERED_FILES_SHOWN = 30


def render_dashboard(wiki_root: str, domain: str) -> str:
    """Render the dashboard Markdown for one project.

    The page declares its kind / domain / scope and is structured so
    a non-technical reader sees: (a) the project's documentation
    completeness in one number, (b) which canonical slots are filled
    vs. empty, (c) how many file-doc pages still carry open gaps,
    (d) direct links into the existing anchor pages.
    """
    wiki_path = Path(wiki_root)
    slot_statuses = _scope_slot_statuses(wiki_root, domain)
    file_cov = audit_files(wiki_root, domain)
    domain_dirs: list[Path] = [
        kd / domain
        for kd in wiki_path.iterdir()
        if kd.is_dir() and not kd.name.startswith((".", "_"))
    ]
    total_pages = 0
    total_gaps = 0
    for d in domain_dirs:
        t, g = _count_curation_gaps_under(d)
        total_pages += t
        total_gaps += g
    kind_counts = _kind_page_counts(wiki_path, domain)

    covered = sum(1 for s in slot_statuses if s.covered)
    total = len(slot_statuses)
    pct = round(100 * covered / total) if total else 0

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {domain} — documentation coverage")
    lines.append("kind: reference")
    lines.append(f"domain: {domain}")
    lines.append("scope: coverage-dashboard")
    lines.append("provenance: auto-generated")
    lines.append("authored_by: wiki-coverage-dashboard-v1")
    lines.append("lifecycle: living")
    lines.append("---")
    lines.append("")
    lines.append(f"# {domain} — documentation coverage")
    lines.append("")
    lines.append(
        f"_This page is auto-generated by the consolidate cycle. It "
        f"shows what's documented for **{domain}** and what isn't yet. "
        f"Nothing here is hand-edited — the headless authoring worker "
        f"drains the gaps below cycle by cycle._"
    )
    lines.append("")

    # Scoreboard
    lines.append("## Coverage at a glance")
    lines.append("")
    lines.append(f"* **Canonical slots filled:** {covered}/{total} ({pct}%)")
    if file_cov.source_root:
        f_total = file_cov.source_file_count
        f_cov = file_cov.covered_file_count
        f_pct = round(100 * f_cov / f_total) if f_total else 0
        lines.append(
            f"* **Source files referenced somewhere:** {f_cov}/{f_total} ({f_pct}%)"
        )
    else:
        lines.append(
            "* **Source files referenced somewhere:** _(no source root resolved)_"
        )
    lines.append(f"* **Total wiki pages for this project:** {total_pages}")
    lines.append(f"* **Open curation gaps awaiting LLM authoring:** {total_gaps}")
    lines.append("")

    # Canonical slots
    lines.append("## Canonical slots")
    lines.append("")
    lines.append("| Slot | Status | Anchor page |")
    lines.append("|---|---|---|")
    for s in slot_statuses:
        if s.covered:
            badge = "✅ filled"
            anchor = (
                f"[`{s.anchor_path}`](../{s.anchor_path})"
                if s.anchor_path
                else f"({s.pages_count} pages)"
            )
        else:
            badge = "✗ **missing — queued**"
            anchor = f"_(will be authored at `{s.suggested_path}`)_"
        lines.append(f"| **{s.title}** | {badge} | {anchor} |")
    lines.append("")

    # Per-slot descriptions for the empty ones
    missing = [s for s in slot_statuses if not s.covered]
    if missing:
        lines.append("## What's still missing — and what should be in each")
        lines.append("")
        for s in missing:
            lines.append(f"### {s.title}")
            lines.append("")
            lines.append(s.description)
            lines.append("")
            lines.append(
                f"_Will be authored at `{s.suggested_path}` by the "
                f"autonomous worker. Status: queued._"
            )
            lines.append("")

    # Page kinds breakdown
    if kind_counts:
        lines.append("## Pages by kind")
        lines.append("")
        lines.append("| Kind | Pages |")
        lines.append("|---|---|")
        for kind, cnt in sorted(kind_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {kind} | {cnt} |")
        lines.append("")

    if file_cov.source_root and file_cov.uncovered_files:
        lines.append("## Source files not yet referenced anywhere")
        lines.append("")
        lines.append(
            f"_{len(file_cov.uncovered_files)} files don't appear in any "
            f"anchor page yet. The autonomous worker will surface them "
            f"as it authors the **services** and **architecture** slots._"
        )
        lines.append("")
        lines.append("```")
        for f in file_cov.uncovered_files[:_UNCOVERED_FILES_SHOWN]:
            lines.append(f)
        if len(file_cov.uncovered_files) > _UNCOVERED_FILES_SHOWN:
            lines.append(
                f"… +{len(file_cov.uncovered_files) - _UNCOVERED_FILES_SHOWN} more"
            )
        lines.append("```")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_dashboards(
    wiki_root: str | Path,
    *,
    domains: Iterable[str] | None = None,
) -> dict[str, str]:
    """Generate one dashboard per project under ``wiki/_dashboards/``.

    Returns a map of ``domain -> written_path`` for the dashboards
    actually emitted. Failures are logged but don't abort the batch.
    """
    wiki_path = Path(wiki_root)
    if not wiki_path.is_dir():
        return {}
    if domains is None:
        try:
            domains = sorted({r.canonical for r in _build_registry().repos})
        except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
            silent_failure.note("wiki_coverage_dashboard.registry", exc)
            return {}
    target_dir = wiki_path / "_dashboards"
    target_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for d in domains:
        page = render_dashboard(str(wiki_path), d)
        path = target_dir / f"{d}.md"
        try:
            path.write_text(page, encoding="utf-8")
            out[d] = str(path)
        except OSError:
            continue
    # Also write an index pointing at each dashboard.
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
