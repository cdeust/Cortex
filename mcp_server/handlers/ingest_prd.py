"""Handler: ingest_prd — pull a PRD document into Cortex's store.

Sources supported
-----------------
- ``path``          — absolute path to a markdown PRD file
- ``content``       — raw markdown string
- ``pipeline_id``   — prd-gen pipeline state id; fetches via upstream MCP

Outputs into Cortex
-------------------
- Wiki page under ``specs/<slug>.md`` (kind=spec)
- One memory for the PRD summary (tagged ``prd``, ``spec``)
- One memory per extracted decision (tagged ``decision``)
- One memory per extracted requirement (tagged ``requirement``)
- Optional validation stats from prd-gen's ``validate_prd_document``

Cortex consumes; prd-gen produces.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.handlers.ingest_helpers import call_upstream, normalise_mcp_payload
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.wiki_store import write_page

logger = logging.getLogger(__name__)

_UPSTREAM_SERVER = "prd-gen"

# ── Schema ──────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Ingest a PRD (Product Requirements Document) into Cortex's "
        "store. Source: a file path, raw markdown, or a prd-gen pipeline "
        "state id (fetched via upstream MCP). Writes the PRD as a wiki "
        "spec page under specs/<slug>.md, extracts decisions and "
        "requirements as separate tagged memories (`decision`, "
        "`requirement`), and optionally routes the document through "
        "prd-gen's `validate_prd_document` to capture quality signals. "
        "Use this after a PRD is authored or generated so Cortex's "
        "Wiki/Board/Knowledge views reflect it. Distinct from "
        "`wiki_write` (manual single-page write, no decision/requirement "
        "extraction), `ingest_codebase` (code symbols, not requirement "
        "documents), and `remember` (one memory, no wiki page or "
        "structured extraction). Mutates wiki/specs/ + memories table. "
        "Latency varies (~500ms-3s depending on validation flag). "
        "Returns {wiki_path, memories_created: {summary, decisions, "
        "requirements}, validation?: stats}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to a markdown PRD file. Mutually exclusive with content/pipeline_id.",
                "examples": ["/Users/alice/code/myapp/docs/prd-auth-v2.md"],
            },
            "content": {
                "type": "string",
                "description": "Raw PRD markdown. Mutually exclusive with path/pipeline_id.",
            },
            "pipeline_id": {
                "type": "string",
                "description": (
                    "prd-gen pipeline state id. When supplied, Cortex calls "
                    "get_pipeline_state to fetch the rendered PRD."
                ),
                "examples": ["prd-pipeline-12345"],
            },
            "title": {
                "type": "string",
                "description": "Override the PRD title (otherwise parsed from the first # heading or filename).",
                "examples": ["Auth v2 redesign"],
            },
            "validate": {
                "type": "boolean",
                "description": (
                    "If true, call prd-gen's validate_prd_document and attach "
                    "validation stats to the ingestion summary."
                ),
                "default": False,
            },
            "domain": {
                "type": "string",
                "description": "Cognitive domain to tag the ingested memories with.",
                "examples": ["myapp", "auth-service"],
            },
        },
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _fetch_prd(args: dict[str, Any]) -> tuple[str, str]:
    """Resolve the PRD markdown + the source label ('path'/'content'/'pipeline_id')."""
    path = (args.get("path") or "").strip()
    content = args.get("content") or ""
    pipeline_id = (args.get("pipeline_id") or "").strip()

    provided = [bool(path), bool(content), bool(pipeline_id)]
    if sum(provided) != 1:
        raise ValueError("exactly one of path / content / pipeline_id must be supplied")

    if path:
        return Path(path).expanduser().read_text(encoding="utf-8"), "path"
    if content:
        return content, "content"

    payload = await call_upstream(
        _UPSTREAM_SERVER,
        "get_pipeline_state",
        {"pipeline_id": pipeline_id},
    )
    result = normalise_mcp_payload(payload)
    prd_text = result.get("rendered_prd") or result.get("prd") or result.get("text")
    if not prd_text:
        raise ValueError(
            f"prd-gen returned no rendered PRD for pipeline_id={pipeline_id}"
        )
    return prd_text, "pipeline_id"


def _extract_title(text: str, override: str | None) -> str:
    """Pick a PRD title: override → first H1 → fallback 'Untitled PRD'."""
    if override:
        return override.strip()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return "Untitled PRD"


_SECTION_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.MULTILINE)


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Return [(heading, body), ...] for H2/H3 sections of the PRD."""
    matches = list(_SECTION_RE.finditer(text))
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if heading and body:
            sections.append((heading, body))
    return sections


_DECISION_HEADINGS = {"decisions", "decision", "architecture decisions"}
_REQUIREMENT_HEADINGS = {
    "requirements",
    "functional requirements",
    "non-functional requirements",
    "acceptance criteria",
    "user stories",
}


def _extract_bullets(body: str) -> list[str]:
    """Pull list bullets out of a section body."""
    out: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            out.append(stripped[2:].strip())
        elif re.match(r"^\d+[.)]\s+", stripped):
            out.append(re.sub(r"^\d+[.)]\s+", "", stripped).strip())
    return [b for b in out if len(b) >= 8]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80] or "prd"


def _render_prd_spec_page(title: str, text: str, source: str) -> tuple[str, str]:
    """Wrap the PRD in a classifier-friendly spec page."""
    slug = _slugify(title)
    rel_path = f"specs/{slug}.md"
    frontmatter = [
        "---",
        f"title: {title}",
        "kind: spec",
        "tags: [prd, spec, ingest]",
        f"source: {source}",
        f"updated: {_now_iso()}",
        "---",
        "",
    ]
    if not text.lstrip().startswith("# "):
        frontmatter.append(f"# {title}")
        frontmatter.append("")
    return rel_path, "\n".join(frontmatter) + text.strip() + "\n"


def _write_bullet_memories(
    store: MemoryStore,
    bullets: list[str],
    tag: str,
    title: str,
    domain: str,
    directory: str,
) -> list[int]:
    """Persist each bullet as a standalone Cortex memory."""
    ids: list[int] = []
    for bullet in bullets:
        content = f"{tag.title()} (from PRD '{title}'): {bullet}"
        record = {
            "content": content,
            "tags": [tag, "prd", "ingest"],
            "source": "ingest_prd",
            "domain": domain,
            "directory_context": directory,
            "importance": 0.7 if tag == "decision" else 0.5,
            "heat": 0.8,
            "is_protected": tag == "decision",
        }
        try:
            mem_id = store.insert_memory(record)
            ids.append(mem_id)
        except Exception as exc:
            logger.debug("%s memory insert failed: %s", tag, exc)
    return ids


async def _maybe_validate(text: str) -> dict[str, Any] | None:
    """Optionally call prd-gen's validate_prd_document; return stats or None."""
    try:
        payload = await call_upstream(
            _UPSTREAM_SERVER,
            "validate_prd_document",
            {"content": text},
        )
        return normalise_mcp_payload(payload)
    except McpConnectionError as exc:
        logger.debug("prd-gen unreachable for validation: %s", exc)
        return {"skipped": True, "reason": "upstream_unreachable"}
    except Exception as exc:
        logger.debug("validate_prd_document failed: %s", exc)
        return {"skipped": True, "reason": f"{type(exc).__name__}"}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ingest a PRD document into Cortex."""
    args = args or {}

    try:
        text, source = await _fetch_prd(args)
    except ValueError as exc:
        return {"ingested": False, "reason": str(exc)}
    except FileNotFoundError as exc:
        return {"ingested": False, "reason": f"prd file not found: {exc}"}
    except McpConnectionError as exc:
        return {
            "ingested": False,
            "reason": "prd_gen_unreachable",
            "error": str(exc),
        }

    title = _extract_title(text, args.get("title"))
    domain = (args.get("domain") or "prd").strip() or "prd"
    directory = str(Path(args.get("path") or ".").expanduser().resolve().parent)

    # 1. Write the spec page.
    rel_path, markdown = _render_prd_spec_page(title, text, source)
    try:
        write_page(WIKI_ROOT, rel_path, markdown, mode="replace")
    except Exception as exc:
        logger.warning("PRD spec page write failed: %s", exc)
        rel_path = None

    # 2. Extract decisions + requirements.
    store = _get_store()
    decision_bullets: list[str] = []
    requirement_bullets: list[str] = []
    for heading, body in _split_sections(text):
        h = heading.lower()
        if h in _DECISION_HEADINGS or any(k in h for k in _DECISION_HEADINGS):
            decision_bullets.extend(_extract_bullets(body))
        elif h in _REQUIREMENT_HEADINGS or any(k in h for k in _REQUIREMENT_HEADINGS):
            requirement_bullets.extend(_extract_bullets(body))

    decision_ids = _write_bullet_memories(
        store, decision_bullets, "decision", title, domain, directory
    )
    requirement_ids = _write_bullet_memories(
        store, requirement_bullets, "requirement", title, domain, directory
    )

    # 3. Summary memory.
    summary_record = {
        "content": f"PRD ingested: '{title}' ({len(decision_bullets)} decisions, "
        f"{len(requirement_bullets)} requirements).",
        "tags": ["prd", "ingest", "summary"],
        "source": "ingest_prd",
        "domain": domain,
        "directory_context": directory,
        "importance": 0.8,
        "heat": 0.9,
        "is_protected": True,
    }
    summary_id: int | None = None
    try:
        summary_id = store.insert_memory(summary_record)
    except Exception as exc:
        logger.debug("PRD summary memory insert failed: %s", exc)

    # 4. Optional validation.
    validation = None
    if args.get("validate"):
        validation = await _maybe_validate(text)

    return {
        "ingested": True,
        "title": title,
        "source": source,
        "wiki_path": rel_path,
        "summary_memory_id": summary_id,
        "decision_count": len(decision_ids),
        "requirement_count": len(requirement_ids),
        "validation": validation,
    }
