"""Wiki page templates + frontmatter parser — pure, deterministic.

Builds the markdown body for each page kind (ADR, spec, file doc, note).
Also parses YAML-style frontmatter (``---``…``---``) into a plain dict so
handlers can round-trip metadata without depending on a YAML library.

Design intent: pages are *authored* content, not derived views. Templates
provide sensible sections; the body is whatever the caller passes in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

ADR_STATUSES = ("proposed", "accepted", "rejected", "superseded", "deprecated")


@dataclass(frozen=True)
class PageDocument:
    """Parsed representation of a wiki page."""

    frontmatter: dict[str, object] = field(default_factory=dict)
    body: str = ""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_frontmatter(fm: dict[str, object]) -> str:
    """Emit a minimal YAML-ish frontmatter block. Sorted keys, scalars only.

    Lists are rendered inline (``[a, b, c]``). Nested dicts are not
    supported — keep metadata flat.
    """
    if not fm:
        return ""
    lines = ["---"]
    for key in sorted(fm):
        value = fm[key]
        if isinstance(value, list):
            rendered = "[" + ", ".join(str(v) for v in value) + "]"
        elif value is None:
            rendered = ""
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _strip_inline_list(value: str) -> list[str]:
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [item.strip() for item in inner.split(",") if item.strip()]


def parse_page(text: str) -> PageDocument:
    """Parse a page's frontmatter + body. Tolerant of missing frontmatter."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return PageDocument(body=text)
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return PageDocument(body=text)
    fm: dict[str, object] = {}
    body_start = len(lines)
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            body_start = idx + 1
            break
        line = lines[idx]
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            fm[key.strip()] = _strip_inline_list(raw)
        else:
            fm[key.strip()] = raw
    body_lines = lines[body_start:]
    while body_lines and body_lines[0] == "":
        body_lines.pop(0)
    return PageDocument(frontmatter=fm, body="\n".join(body_lines))


def render_page(doc: PageDocument) -> str:
    """Render a PageDocument back to markdown text."""
    header = _format_frontmatter(doc.frontmatter)
    if header and doc.body:
        return header + doc.body + ("" if doc.body.endswith("\n") else "\n")
    if header:
        return header
    return doc.body + ("" if doc.body.endswith("\n") else "\n") if doc.body else ""


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
    body = (
        f"# {title}\n\n"
        f"## Rule\n\n{rule}\n\n"
        f"## Rationale\n\n{rationale}\n"
    )
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


def build_index(page_paths: list[str]) -> str:
    """Build a structured INDEX.md grouped by domain then kind.

    Each path is relative to the wiki root. Supports both flat
    (``notes/foo.md``) and domain-scoped (``notes/cortex/foo.md``) paths.
    Pure function — no I/O.
    """
    from mcp_server.core.wiki_layout import PAGE_KINDS

    # Parse paths into (kind, domain, filename, full_path)
    entries: list[tuple[str, str, str, str]] = []
    for p in page_paths:
        parts = p.split("/")
        if len(parts) >= 2 and parts[0] in PAGE_KINDS:
            kind = parts[0]
            if len(parts) >= 3:
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

    lines = [
        "# Cortex Knowledge Base",
        "",
        f"**{total} pages** across {domain_count} domains",
        "",
    ]

    # Render each domain
    for domain in sorted(tree.keys(), key=lambda d: ("zzz" if d == "_general" else d)):
        kinds = tree[domain]
        page_count = sum(len(pages) for pages in kinds.values())
        label = "Global" if domain == "_general" else domain.replace("-", " ").title()
        lines.append(f"## {label} ({page_count} pages)")
        lines.append("")

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

    return "\n".join(lines)
