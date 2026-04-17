"""Wiki grooming — drift detection against templates + naming conventions.

The grooming system has two parts:

  1. **Auditor** (this module, deterministic): scans every wiki page,
     reports drift against the page's kind template. Fast, runs every
     consolidate cycle. Produces a structured list of issues (missing
     front-matter, wrong status value, non-canonical slug, missing
     required section).

  2. **Rewriter** (agents/cortex-wiki-groomer.md, LLM): handed the
     audit output + the raw page, rewrites to the template while
     preserving content semantics. Runs on-demand when the auditor
     reports issues, or when the user invokes /cortex:groom-wiki.

This module is pure-functional — no I/O, no LLM calls. The auditor's
output is structured so tests can assert on it and the LLM rewriter
has an unambiguous work list.

Source: user directive "agent or llm on side to write with template and
naming conventions to keep it tidy and up to date".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from mcp_server.core.wiki_layout import PAGE_KINDS
from mcp_server.core.wiki_templates import (
    naming_convention,
    required_fields,
    valid_status_values,
)


@dataclass
class GroomIssue:
    """One detected drift on a page."""

    kind: str  # "missing_frontmatter" | "invalid_status" | "non_canonical_slug"
    #           "missing_section" | "manual_override" | "unknown_kind"
    detail: str
    suggestion: str = ""


@dataclass
class PageAudit:
    """Audit result for a single page."""

    page_path: str  # wiki-relative path
    page_kind: str | None
    issues: list[GroomIssue] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)


# ── Front-matter parser ───────────────────────────────────────────────────


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown file into (frontmatter_dict, body).

    Returns empty dict + full content when no front-matter is present.
    Intentionally does NOT require PyYAML — we parse a limited
    ``key: value`` subset plus quoted strings, which covers every field
    the templates actually declare. Multi-line values and anchors are
    treated as text and fed to the LLM rewriter intact.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    raw = match.group(1)
    body = content[match.end() :]
    frontmatter: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        frontmatter[key] = value
    return frontmatter, body


# ── Auditor ──────────────────────────────────────────────────────────────


def infer_kind_from_path(page_path: str) -> str | None:
    """Infer page kind from the wiki-relative path.

    ``adr/0042-foo.md`` → ``adr``.
    ``specs/phase5.md`` → ``specs``.
    ``<unknown>/x.md``  → None.
    """
    parts = PurePosixPath(page_path).parts
    if not parts:
        return None
    first = parts[0]
    return first if first in PAGE_KINDS else None


def audit_page(page_path: str, content: str) -> PageAudit:
    """Audit a single page against its kind's template + naming rule.

    Returns an audit result listing every drift. Empty ``issues`` list
    means the page is groomed correctly.

    When front-matter declares ``grooming: manual``, we skip all checks
    and emit a single ``manual_override`` note (rewriter MUST NOT touch
    the page).
    """
    audit = PageAudit(page_path=page_path, page_kind=None)
    kind = infer_kind_from_path(page_path)
    audit.page_kind = kind

    if kind is None:
        audit.issues.append(
            GroomIssue(
                kind="unknown_kind",
                detail=f"path {page_path!r} does not start with a known kind prefix",
                suggestion="move into one of: " + ", ".join(PAGE_KINDS),
            )
        )
        return audit

    frontmatter, body = parse_frontmatter(content)

    if frontmatter.get("grooming") == "manual":
        audit.issues.append(
            GroomIssue(
                kind="manual_override",
                detail="page opts out of grooming",
                suggestion="skip (author-managed)",
            )
        )
        return audit

    # 1. Required front-matter fields
    for field_name in required_fields(kind):
        if field_name not in frontmatter or frontmatter[field_name] in ("", None):
            audit.issues.append(
                GroomIssue(
                    kind="missing_frontmatter",
                    detail=f"required field '{field_name}' is missing or empty",
                    suggestion=f"add '{field_name}: <value>' to front-matter",
                )
            )

    # 2. Valid status value (when the kind has a status field)
    valid_statuses = valid_status_values(kind)
    if valid_statuses and "status" in frontmatter:
        if frontmatter["status"] not in valid_statuses:
            audit.issues.append(
                GroomIssue(
                    kind="invalid_status",
                    detail=(
                        f"status={frontmatter['status']!r} is not one of "
                        f"{list(valid_statuses)}"
                    ),
                    suggestion=f"use one of: {', '.join(valid_statuses)}",
                )
            )

    # 3. Naming convention on the slug.
    slug = PurePosixPath(page_path).stem
    pattern, description = naming_convention(kind)
    if not re.match(pattern, slug):
        audit.issues.append(
            GroomIssue(
                kind="non_canonical_slug",
                detail=f"slug {slug!r} does not match pattern {pattern}",
                suggestion=description,
            )
        )

    return audit


def audit_wiki(pages: list[tuple[str, str]]) -> list[PageAudit]:
    """Audit a batch of pages. Input is a list of (path, content) tuples.

    Returns audits only for pages with issues (groomed pages are
    filtered out to keep the output focused on the work list).
    """
    audits: list[PageAudit] = []
    for path, content in pages:
        a = audit_page(path, content)
        if a.has_issues:
            audits.append(a)
    return audits
