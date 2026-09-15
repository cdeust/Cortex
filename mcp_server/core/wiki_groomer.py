"""Wiki grooming — drift detection against templates + naming conventions.

source: ADR-0303"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mcp_server.shared.wiki_layout import PAGE_KINDS
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


def page_audit_has_issues(audit: "PageAudit") -> bool:
    """Return whether the page audit contains any issues.

    source: ADR-0303
    """
    return bool(audit.issues)


# ── Front-matter parser ───────────────────────────────────────────────────


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# source: ADR-0303

_MIN_QUOTED_SCALAR_LEN = 2


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
        if (
            len(value) >= _MIN_QUOTED_SCALAR_LEN
            and value[0] == value[-1]
            and value[0] in "'\""
        ):
            value = value[1:-1]
        frontmatter[key] = value
    return frontmatter, body


# ── Auditor ──────────────────────────────────────────────────────────────


def _first_path_segment(path: str) -> str | None:
    """Pure-string equivalent of ``PurePosixPath(path).parts[0]`` for a
    relative path (core may not import pathlib; issue #560)."""
    segments = [s for s in path.split("/") if s]
    return segments[0] if segments else None


def _path_stem(path: str) -> str:
    """Pure-string equivalent of ``PurePosixPath(path).stem`` (core may not
    import pathlib; issue #560)."""
    name = path.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[:dot] if dot > 0 else name


def infer_kind_from_path(page_path: str) -> str | None:
    """Infer page kind from the wiki-relative path.

    ``adr/0042-foo.md`` → ``adr``.
    ``specs/phase5.md`` → ``specs``.
    ``<unknown>/x.md``  → None.
    """
    first = _first_path_segment(page_path)
    if first is None:
        return None
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
    slug = _path_stem(page_path)
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

    source: ADR-0303"""
    audits: list[PageAudit] = []
    for path, content in pages:
        a = audit_page(path, content)
        if page_audit_has_issues(a):
            audits.append(a)
    return audits
