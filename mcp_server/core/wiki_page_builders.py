"""Wiki page builders — pure, deterministic.

Builds the markdown body for each page kind (ADR, spec, file doc, note,
lesson, convention, reference). Templates provide sensible sections; the
body is whatever the caller passes in.
"""

from __future__ import annotations

from mcp_server.core.wiki_frontmatter import PageDocument, _now_iso, render_page

ADR_STATUSES = ("proposed", "accepted", "rejected", "superseded", "deprecated")


def build_adr(
    *,
    number: int,
    title: str,
    context: str,
    decision: str,
    consequences: str,
    status: str = "accepted",
    tags: list[str] | None = None,
) -> str:
    """Render an ADR page body + frontmatter."""
    if status not in ADR_STATUSES:
        raise ValueError(f"unknown ADR status: {status}")
    fm = {
        "kind": "adr",
        "number": f"{number:04d}",
        "title": title,
        "status": status,
        "created": _now_iso(),
        "tags": tags or ["adr"],
    }
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"## Status\n\n{status}\n\n"
        f"## Context\n\n{context}\n\n"
        f"## Decision\n\n{decision}\n\n"
        f"## Consequences\n\n{consequences}\n"
    )
    return render_page(PageDocument(frontmatter=fm, body=body))


def build_spec(
    *,
    title: str,
    summary: str,
    body: str = "",
    tags: list[str] | None = None,
) -> str:
    """Render a spec / PRD / design doc page."""
    fm = {
        "kind": "spec",
        "title": title,
        "created": _now_iso(),
        "tags": tags or ["spec"],
    }
    page_body = f"# {title}\n\n## Summary\n\n{summary}\n"
    if body:
        page_body += f"\n## Detail\n\n{body}\n"
    return render_page(PageDocument(frontmatter=fm, body=page_body))


def build_file_doc(
    *,
    file_path: str,
    purpose: str,
    body: str = "",
    tags: list[str] | None = None,
) -> str:
    """Render a per-source-file documentation page."""
    fm = {
        "kind": "file",
        "file": file_path,
        "created": _now_iso(),
        "tags": tags or ["file"],
    }
    page_body = f"# `{file_path}`\n\n## Purpose\n\n{purpose}\n"
    if body:
        page_body += f"\n## Notes\n\n{body}\n"
    return render_page(PageDocument(frontmatter=fm, body=page_body))


def build_note(
    *,
    title: str,
    body: str,
    tags: list[str] | None = None,
    updated: str | None = None,
) -> str:
    """Render a free-form note / investigation."""
    fm: dict[str, object] = {
        "kind": "note",
        "title": title,
        "created": _now_iso(),
        "tags": tags or ["note"],
    }
    if updated:
        fm["updated"] = updated
    return render_page(PageDocument(frontmatter=fm, body=f"# {title}\n\n{body}\n"))


def maturity_label(source_count: int) -> str:
    """Compute maturity from number of source memories."""
    if source_count >= 8:
        return "stable"
    if source_count >= 4:
        return "reviewed"
    if source_count >= 2:
        return "draft"
    return "stub"


def _sources_section(source_ids: list[int | str] | None) -> str:
    """Render a Sources section from memory IDs."""
    if not source_ids:
        return "\n## Sources\n\n*Auto-generated from memory system.*\n"
    items = "\n".join(f"- Memory #{sid}" for sid in source_ids)
    return f"\n## Sources\n\n{items}\n"


def _related_section() -> str:
    """Empty Related section — filled by auto-linking."""
    return "\n## Related\n\n*No cross-links yet.*\n"


def build_lesson(
    *,
    title: str,
    situation: str,
    mistake: str,
    fix: str,
    rule: str,
    domain: str = "",
    tags: list[str] | None = None,
    created: str | None = None,
    updated: str | None = None,
    source_ids: list[int | str] | None = None,
) -> str:
    """Render a lesson-learned page."""
    sc = len(source_ids) if source_ids else 1
    fm: dict[str, object] = {
        "kind": "lesson",
        "title": title,
        "domain": domain,
        "created": created or _now_iso(),
        "maturity": maturity_label(sc),
        "source_count": sc,
        "tags": tags or ["lesson"],
    }
    if updated:
        fm["updated"] = updated
    body = (
        f"# {title}\n\n"
        f"## Situation\n\n{situation}\n\n"
        f"## What Went Wrong\n\n{mistake}\n\n"
        f"## Fix Applied\n\n{fix}\n\n"
        f"## Rule for the Future\n\n{rule}\n"
        + _sources_section(source_ids)
        + _related_section()
    )
    return render_page(PageDocument(frontmatter=fm, body=body))


def build_convention(
    *,
    title: str,
    rule: str,
    rationale: str,
    scope: str = "",
    domain: str = "",
    tags: list[str] | None = None,
    created: str | None = None,
    updated: str | None = None,
    source_ids: list[int | str] | None = None,
) -> str:
    """Render a convention/standard page."""
    sc = len(source_ids) if source_ids else 1
    fm: dict[str, object] = {
        "kind": "convention",
        "title": title,
        "domain": domain,
        "created": created or _now_iso(),
        "maturity": maturity_label(sc),
        "source_count": sc,
        "tags": tags or ["convention"],
    }
    if updated:
        fm["updated"] = updated
    body = f"# {title}\n\n## Rule\n\n{rule}\n\n## Rationale\n\n{rationale}\n"
    if scope:
        body += f"\n## Scope\n\n{scope}\n"
    body += _sources_section(source_ids) + _related_section()
    return render_page(PageDocument(frontmatter=fm, body=body))


def build_reference(
    *,
    title: str,
    overview: str,
    architecture: str = "",
    api: str = "",
    domain: str = "",
    tags: list[str] | None = None,
    created: str | None = None,
    updated: str | None = None,
    source_ids: list[int | str] | None = None,
) -> str:
    """Render a reference page — current truth about a component."""
    sc = len(source_ids) if source_ids else 1
    fm: dict[str, object] = {
        "kind": "reference",
        "title": title,
        "domain": domain,
        "created": created or _now_iso(),
        "maturity": maturity_label(sc),
        "source_count": sc,
        "tags": tags or ["reference"],
    }
    if updated:
        fm["updated"] = updated
    body = f"# {title}\n\n## Overview\n\n{overview}\n"
    if architecture:
        body += f"\n## Architecture\n\n{architecture}\n"
    if api:
        body += f"\n## API / Interface\n\n{api}\n"
    body += _sources_section(source_ids) + _related_section()
    return render_page(PageDocument(frontmatter=fm, body=body))
