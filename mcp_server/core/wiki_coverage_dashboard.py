"""Per-project coverage dashboard.

source: ADR-0298"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from mcp_server.core.wiki_coverage import (
    audit_domain,
    audit_files,
)
from mcp_server.observability import silent_failure
from mcp_server.shared.domain_mapping import _build_registry

# Composition-root injection seam (core may not import os/pathlib or
# perform I/O; issue #560). Real implementations live in
# mcp_server/infrastructure/wiki_dashboard_fs.py, wired once via
# configure_dashboard_filesystem (mcp_server/__main__.py for production,
# tests_py/conftest.py for the test session).
CountGaps = Callable[[str], "tuple[int, int]"]
KindPageCounts = Callable[[str, str], "dict[str, int]"]
DomainDirsUnder = Callable[[str, str], "list[str]"]
IsDir = Callable[[str], bool]
WriteDashboardPages = Callable[[str, "dict[str, str]"], "dict[str, str]"]

_count_curation_gaps: CountGaps | None = None
_kind_page_counts_provider: KindPageCounts | None = None
_domain_dirs_under: DomainDirsUnder | None = None
_wiki_root_is_dir: IsDir | None = None
_write_dashboard_pages: WriteDashboardPages | None = None


def configure_dashboard_filesystem(
    *,
    count_curation_gaps: CountGaps,
    kind_page_counts: KindPageCounts,
    domain_dirs_under: DomainDirsUnder,
    wiki_root_is_dir: IsDir,
    write_dashboard_pages: WriteDashboardPages,
) -> None:
    """Composition-root hook: register the real dashboard filesystem ops.

    source: ADR-0298 (issue #560)"""
    global \
        _count_curation_gaps, \
        _kind_page_counts_provider, \
        _domain_dirs_under, \
        _wiki_root_is_dir, \
        _write_dashboard_pages
    _count_curation_gaps = count_curation_gaps
    _kind_page_counts_provider = kind_page_counts
    _domain_dirs_under = domain_dirs_under
    _wiki_root_is_dir = wiki_root_is_dir
    _write_dashboard_pages = write_dashboard_pages


def _unconfigured(what: str) -> RuntimeError:
    return RuntimeError(
        f"wiki_coverage_dashboard {what} provider not configured — call "
        "configure_dashboard_filesystem() at the composition root first"
    )


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


def _count_curation_gaps_under(domain_dir: str) -> tuple[int, int]:
    """Walk a domain's pages and return ``(total_pages, total_open_gaps)``.

    source: ADR-0298"""
    if _count_curation_gaps is None:
        raise _unconfigured("count_curation_gaps")
    return _count_curation_gaps(str(domain_dir))


def _kind_page_counts(wiki_root: str, domain: str) -> dict[str, int]:
    """Count pages per kind directory for a domain.

    source: ADR-0298"""
    if _kind_page_counts_provider is None:
        raise _unconfigured("kind_page_counts")
    return _kind_page_counts_provider(str(wiki_root), domain)


# source: ADR-0298

# source: ADR-0298
_UNCOVERED_FILES_SHOWN = 30


def render_dashboard(wiki_root: str, domain: str) -> str:
    """Render the dashboard Markdown for one project.

    source: ADR-0298"""
    if _domain_dirs_under is None:
        raise _unconfigured("domain_dirs_under")
    slot_statuses = _scope_slot_statuses(wiki_root, domain)
    file_cov = audit_files(wiki_root, domain)
    domain_dirs = _domain_dirs_under(str(wiki_root), domain)
    total_pages = 0
    total_gaps = 0
    for d in domain_dirs:
        t, g = _count_curation_gaps_under(d)
        total_pages += t
        total_gaps += g
    kind_counts = _kind_page_counts(wiki_root, domain)

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
    wiki_root: str,
    *,
    domains: Iterable[str] | None = None,
) -> dict[str, str]:
    """Generate one dashboard per project under ``wiki/_dashboards/``.

    Returns a map of ``domain -> written_path`` for the dashboards
    actually emitted. Failures are logged but don't abort the batch.
    """
    if _wiki_root_is_dir is None or _write_dashboard_pages is None:
        raise _unconfigured("wiki_root_is_dir/write_dashboard_pages")
    if not _wiki_root_is_dir(str(wiki_root)):
        return {}
    if domains is None:
        try:
            domains = sorted({r.canonical for r in _build_registry().repos})
        except Exception as exc:  # noqa: BLE001 — source: ADR-0298
            silent_failure.note("wiki_coverage_dashboard.registry", exc)
            return {}
    pages = {d: render_dashboard(str(wiki_root), d) for d in domains}
    return _write_dashboard_pages(str(wiki_root), pages)
