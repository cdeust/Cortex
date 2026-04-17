"""Wiki README generation — plain-language top-level entry point.

The wiki's technical content lives in `<kind>/<domain>/<slug>.md` files
with templated front-matter + section structure — tech-ready, but dense.
This module generates a top-level ``README.md`` that is readable by
non-technical stakeholders:

  * What the wiki IS (one paragraph, plain language).
  * What lives WHERE (kind-labelled sections with a 1-line "what it's
    for" summary, not "architecture decision record" jargon).
  * How to NAVIGATE (auto-generated table of contents + link to the
    detailed technical INDEX.md).
  * When it was last GROOMED (builds trust: "this is current").

Design principle: non-tech readers see plain language at the top;
tech readers follow links down to the structured INDEX + per-page
templates. No information is hidden from either audience — just
presented at the right depth for each click.

Source: user directive "wiki generation, folder and file management,
keep this tidy, in order, readable by non tech while having all
information needed for tech people".
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import PurePosixPath

from mcp_server.core.wiki_layout import PAGE_KINDS

# Non-tech label + one-line description per kind. The description is
# what a first-time reader needs to know to decide "do I click here?".
_KIND_PLAIN: dict[str, tuple[str, str]] = {
    "adr": (
        "Architecture Decisions",
        "Why we chose X over Y — the reasoning behind major design "
        "choices. Read these to understand WHY the system looks the "
        "way it does.",
    ),
    "specs": (
        "Specifications & Designs",
        "What we plan to build before we build it — feature specs, "
        "design docs, PRDs. Read these to understand WHAT is coming.",
    ),
    "guides": (
        "Guides & How-To",
        "Step-by-step instructions for common tasks. Read these when "
        "you want to DO something.",
    ),
    "reference": (
        "Reference",
        "API signatures, configuration keys, protocol formats. Read "
        "these to LOOK UP an exact detail.",
    ),
    "conventions": (
        "Conventions",
        "The rules the team follows (naming, style, contribution "
        "process). Read these before proposing changes.",
    ),
    "lessons": (
        "Lessons Learned",
        "Mistakes, root causes, and rules we now follow to avoid "
        "repeating them. Read these to learn from past incidents.",
    ),
    "notes": (
        "Notes & Investigations",
        "Work-in-progress thinking, exploratory analyses. Read these "
        "for context on ongoing work.",
    ),
    "journal": (
        "Journal",
        "Time-stamped entries of events, experiments, and sessions. "
        "Read these for what happened and when.",
    ),
    "files": (
        "File Documentation",
        "Per-source-file documentation (auto-generated from code "
        "analysis). Read these for a map of the codebase.",
    ),
}


def _count_pages(page_paths: list[str]) -> dict[str, int]:
    """Count pages per kind. Only kinds with >0 pages are returned."""
    counts: dict[str, int] = defaultdict(int)
    for p in page_paths:
        first = PurePosixPath(p).parts[0] if p else ""
        if first in PAGE_KINDS:
            counts[first] += 1
    return dict(counts)


def _count_by_domain(page_paths: list[str]) -> dict[str, int]:
    """Count pages per domain, excluding the catch-all ``_general``."""
    counts: dict[str, int] = defaultdict(int)
    for p in page_paths:
        parts = PurePosixPath(p).parts
        if len(parts) < 3:
            continue  # root-level or missing domain
        if parts[0] not in PAGE_KINDS:
            continue
        counts[parts[1]] += 1
    return dict(counts)


def build_plain_readme(
    page_paths: list[str],
    *,
    project_name: str = "Cortex",
    generated_at: datetime | None = None,
) -> str:
    """Generate the top-level plain-language README.md for the wiki.

    Pure function — takes a list of wiki-relative page paths, returns
    Markdown. Caller writes to ``<wiki_root>/README.md``.

    The output is stable (same input → same output, modulo the
    ``generated_at`` timestamp) so it's safe to write on every
    reindex without churning the git log.
    """
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)

    total = len([p for p in page_paths if p and not p.startswith(".generated/")])
    kind_counts = _count_pages(page_paths)
    domain_counts = _count_by_domain(page_paths)

    lines: list[str] = []
    lines.append(f"# {project_name} Wiki")
    lines.append("")
    lines.append(
        "This is your project's **living knowledge base** — "
        "decisions, plans, how-tos, and lessons, kept tidy automatically "
        "as the work happens."
    )
    lines.append("")
    lines.append(
        f"There are currently **{total} page{'s' if total != 1 else ''}** "
        f"across **{len(kind_counts)} categories**"
        + (f" and **{len(domain_counts)} domains**." if domain_counts else ".")
    )
    lines.append("")
    lines.append(f"_Last groomed: {generated_at.strftime('%Y-%m-%d %H:%M UTC')}._")
    lines.append("")

    # --- What's here, by category ---
    lines.append("## What's here")
    lines.append("")
    for kind in PAGE_KINDS:
        if kind_counts.get(kind, 0) == 0:
            continue
        label, description = _KIND_PLAIN[kind]
        count = kind_counts[kind]
        lines.append(f"### {label} ({count} page{'s' if count != 1 else ''})")
        lines.append("")
        lines.append(description)
        lines.append("")
        lines.append(f"→ Folder: [`{kind}/`](./{kind}/)")
        lines.append("")

    # --- Domains ---
    if domain_counts:
        lines.append("## Covered domains")
        lines.append("")
        lines.append(
            "Each domain is a distinct area of the project. Pages are "
            "filed under `<category>/<domain>/<page>.md`."
        )
        lines.append("")
        for domain, count in sorted(domain_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- **{domain}** — {count} page{'s' if count != 1 else ''}")
        lines.append("")

    # --- Navigation ---
    lines.append("## Go deeper")
    lines.append("")
    lines.append(
        "The full table of contents (grouped by domain and category) "
        "lives at [`.generated/INDEX.md`](./.generated/INDEX.md). "
        "It's rebuilt automatically on every wiki write."
    )
    lines.append("")
    lines.append(
        "Every page follows a consistent template per category — see "
        "the [conventions folder](./conventions/) (if present) for the rules."
    )
    lines.append("")

    # --- For tech readers ---
    lines.append("## For contributors")
    lines.append("")
    lines.append(
        "Pages are groomed by `cortex-wiki-groomer` (runs asynchronously "
        "during `cortex:consolidate`). The groomer:"
    )
    lines.append("")
    lines.append("- Preserves every paragraph you wrote (no information loss).")
    lines.append("- Fills missing front-matter from context (or marks `unknown`).")
    lines.append("- Enforces naming conventions (kebab-slugs, 4-digit ADR IDs).")
    lines.append("- Skips any page whose front-matter declares `grooming: manual`.")
    lines.append("")
    lines.append(
        "To opt a page out of grooming, add `grooming: manual` to its "
        "front-matter. Nothing you write by hand will ever be rewritten "
        "without your consent."
    )
    lines.append("")

    return "\n".join(lines) + "\n"
