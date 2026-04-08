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
) -> str:
    """Render a free-form note / investigation."""
    fm = {
        "kind": "note",
        "title": title,
        "created": _now_iso(),
        "tags": tags or ["note"],
    }
    return render_page(PageDocument(frontmatter=fm, body=f"# {title}\n\n{body}\n"))
