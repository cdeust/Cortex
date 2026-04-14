"""Phase 2.5 — Compile approved DraftPages to markdown files.

Pure function: given an approved draft + kind metadata + domain,
produce (rel_path, markdown_text). The handler atomically writes
the file via wiki_store and persists the wiki.pages mirror row.

Frontmatter mirrors wiki.pages columns. Body is:

    # <title>

    <lead>

    ## <section heading>

    <section body>

    ...

    ## See also              ← only when wiki.links references exist

LaTeX-style frontend (preserved per user requirement) renders this
without any further per-kind formatting — the renderer is style-only.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from mcp_server.core.wiki_layout import slugify

_FRONTMATTER_KEYS_ORDER = (
    "title",
    "kind",
    "domain",
    "domains",
    "tags",
    "audience",
    "requires",
    "status",
    "lifecycle_state",
    "supersedes",
    "superseded_by",
    "verified",
    "concept_id",
    "memory_id",
    "draft_id",
    "synth_model",
    "created",
    "updated",
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yaml_value(v):
    """Render a Python value as a YAML inline value our parser supports."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_yaml_value(x).strip('"') for x in v) + "]"
    s = str(v)
    if any(ch in s for ch in (":", "#", "\n")) or s.startswith(("[", "{", "-", "?")):
        return f'"{s}"'
    return s


def _build_frontmatter(meta: dict) -> str:
    lines = ["---"]
    seen: set[str] = set()
    for key in _FRONTMATTER_KEYS_ORDER:
        if key in meta and meta[key] is not None and meta[key] != "":
            lines.append(f"{key}: {_yaml_value(meta[key])}")
            seen.add(key)
    for key, val in meta.items():
        if key in seen or val is None or val == "":
            continue
        lines.append(f"{key}: {_yaml_value(val)}")
    lines.append("---")
    return "\n".join(lines)


def _section_md(heading: str, body: str) -> str:
    body = (body or "").strip()
    return f"## {heading}\n\n{body}\n"


def derive_rel_path(
    *,
    kind: str,
    domain: str,
    title: str,
    memory_id: int | None,
    concept_id: int | None,
    kind_dir: str | None = None,
) -> str:
    """Compute the canonical filesystem path for a compiled page.

    Mirrors the convention of the existing wiki_sync layout:
      <kind_dir>/<domain_slug>/<id_prefix>-<title_slug>.md

    id_prefix is preferred over a flat slug to make filenames stable
    even when titles drift.
    """
    title_slug = slugify(title or "untitled")
    domain_slug = slugify(domain or "_general", max_len=40)
    folder = kind_dir or {
        "adr": "adr",
        "spec": "specs",
        "lesson": "lessons",
        "convention": "conventions",
        "note": "notes",
        "guide": "guides",
        "reference": "reference",
    }.get(kind, "notes")
    id_prefix = (
        f"{memory_id}"
        if memory_id is not None
        else (f"c{concept_id}" if concept_id is not None else "x")
    )
    return f"{folder}/{domain_slug}/{id_prefix}-{title_slug}.md"


def compile_draft(
    draft: dict,
    *,
    domain: str = "_general",
    kind_dir: str | None = None,
    backlinks: list[dict] | None = None,
) -> tuple[str, str, dict]:
    """Compile an approved DraftPage to (rel_path, markdown, frontmatter).

    Inputs:
      - draft: dict from wiki.drafts (id, title, kind, lead, sections,
               concept_id, memory_id, frontmatter, synth_model, ...)
      - domain: target domain slug (caller picks; usually inherited from
                the source memory)
      - kind_dir: override the kind → directory mapping
      - backlinks: optional [{slug, title, link_kind}] to render in a
                   "## See also" footer

    Returns (rel_path, markdown_text, frontmatter_dict). The handler
    writes the file and updates wiki.pages.
    """
    title = draft.get("title", "Untitled")
    kind = draft.get("kind", "note")
    lead = (draft.get("lead", "") or "").strip()
    sections = draft.get("sections", []) or []
    fm_existing = draft.get("frontmatter") or {}

    rel_path = derive_rel_path(
        kind=kind,
        domain=domain,
        title=title,
        memory_id=draft.get("memory_id"),
        concept_id=draft.get("concept_id"),
        kind_dir=kind_dir,
    )

    now = _now_iso()
    frontmatter: dict = {
        "title": title,
        "kind": kind,
        "domain": domain,
        "status": fm_existing.get("status", "seedling"),
        "lifecycle_state": fm_existing.get("lifecycle_state", "active"),
        "memory_id": draft.get("memory_id"),
        "concept_id": draft.get("concept_id"),
        "draft_id": draft.get("id"),
        "synth_model": draft.get("synth_model"),
        "created": fm_existing.get("created", now),
        "updated": now,
    }
    # Preserve any other fields the synthesiser provided
    for k, v in fm_existing.items():
        frontmatter.setdefault(k, v)

    body_parts: list[str] = []
    body_parts.append(f"# {title}\n")
    if lead:
        body_parts.append(f"{lead}\n")
    for s in sections:
        heading = s.get("heading") if isinstance(s, dict) else getattr(s, "heading", "")
        body = s.get("body") if isinstance(s, dict) else getattr(s, "body", "")
        if not heading:
            continue
        body_parts.append(_section_md(heading, body))

    if backlinks:
        body_parts.append("## See also\n")
        for b in backlinks:
            slug = b.get("slug", "")
            label = b.get("title", slug)
            kind_hint = b.get("link_kind") or ""
            suffix = (
                f" _({kind_hint})_" if kind_hint and kind_hint != "see-also" else ""
            )
            body_parts.append(f"- [[{slug}|{label}]]{suffix}\n")

    md = _build_frontmatter(frontmatter) + "\n\n" + "\n".join(body_parts)
    # Normalise trailing whitespace
    md = re.sub(r"\n{3,}", "\n\n", md).rstrip() + "\n"

    return rel_path, md, frontmatter
