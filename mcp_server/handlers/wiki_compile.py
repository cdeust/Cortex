"""Wiki Phase 2.5 — Compile approved drafts to .md files.

For every approved draft that has not yet been published:
  1. Resolve the target domain (from source memory or 'unknown')
  2. Compile draft → (rel_path, markdown, frontmatter)
  3. Atomic write via wiki_store.write_page (mode='replace')
  4. Upsert wiki.pages with the new content (matches the file)
  5. Transition draft status pending/approved → published
  6. Memo the publication event

Composition root — never raises per-draft; collects errors.

Modes:
  publish all approved:  wiki_compile({})
  publish one draft:     wiki_compile({"draft_id": 42})
  dry-run preview:       wiki_compile({"draft_id": 42, "dry_run": true})
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.draft_compiler import compile_draft
from mcp_server.core.wiki_layout import slugify
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    body_hash,
    get_draft,
    insert_memo,
    list_drafts,
    update_draft_status,
    upsert_page,
)
from mcp_server.infrastructure.wiki_store import write_page


schema = {
    "description": (
        "Compile approved drafts to .md files in the wiki folder and "
        "upsert wiki.pages mirror rows. Phase 2.5 of the redesign."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "draft_id": {"type": "integer"},
            "dry_run": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 100},
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


def _domain_for_memory(conn, memory_id: int | None) -> str:
    """Look up the domain of a source memory; default to '_general'."""
    if memory_id is None:
        return "_general"
    with conn.cursor() as cur:
        cur.execute("SELECT domain FROM memories WHERE id = %s", (memory_id,))
        row = cur.fetchone()
    if not row:
        return "_general"
    domain = row["domain"] if isinstance(row, dict) else row[0]
    return domain or "_general"


def _approved_drafts(conn, draft_id: int | None, limit: int) -> list[dict]:
    if draft_id is not None:
        d = get_draft(conn, draft_id)
        return [d] if d else []
    return list_drafts(conn, status="approved", limit=limit)


def _publish_one(conn, draft: dict, *, dry_run: bool) -> dict:
    domain = _domain_for_memory(conn, draft.get("memory_id"))
    rel_path, markdown, frontmatter = compile_draft(draft, domain=domain)

    if dry_run:
        return {
            "draft_id": draft["id"],
            "rel_path": rel_path,
            "bytes": len(markdown.encode("utf-8")),
            "preview": markdown[:280],
            "dry_run": True,
        }

    # 1. Atomic write to disk (source of truth)
    write_page(WIKI_ROOT, rel_path, markdown, mode="replace")

    # 2. Build the wiki.pages mirror payload
    page_row = {
        "memory_id": draft.get("memory_id"),
        "concept_id": draft.get("concept_id"),
        "rel_path": rel_path,
        "slug": slugify(draft.get("title") or "untitled"),
        "kind": draft.get("kind"),
        "title": draft.get("title", "Untitled"),
        "domain": domain,
        "domains": [domain] if domain else [],
        "tags": (draft.get("frontmatter") or {}).get("tags", []),
        "audience": (draft.get("frontmatter") or {}).get("audience", []),
        "requires": (draft.get("frontmatter") or {}).get("requires", []),
        "status": frontmatter.get("status", "seedling"),
        "lifecycle_state": frontmatter.get("lifecycle_state", "active"),
        "lead": (draft.get("lead") or "").strip(),
        "sections": {
            (s.get("heading") if isinstance(s, dict) else getattr(s, "heading", "")): (
                s.get("body") if isinstance(s, dict) else getattr(s, "body", "")
            )
            for s in (draft.get("sections") or [])
        },
        "body": markdown,
        "body_hash": body_hash(markdown),
    }
    page_id, was_modified = upsert_page(conn, page_row)

    # 3. Transition the draft → published, link the page
    update_draft_status(
        conn, draft["id"], status="published", published_page_id=page_id
    )

    # 4. Memo
    insert_memo(
        conn,
        subject_type="page",
        subject_id=page_id,
        decision="published_from_draft",
        rationale=f"Compiled draft {draft['id']} ({draft.get('kind')}) → {rel_path}",
        inputs={
            "draft_id": draft["id"],
            "synth_model": draft.get("synth_model"),
            "rel_path": rel_path,
        },
        confidence=draft.get("confidence", 0.5),
        author="compiler",
    )

    return {
        "draft_id": draft["id"],
        "page_id": page_id,
        "rel_path": rel_path,
        "page_modified": was_modified,
    }


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    store = _get_store()
    conn = store._conn

    drafts = _approved_drafts(conn, args.get("draft_id"), int(args.get("limit", 100)))
    if not drafts:
        return {
            "drafts_published": 0,
            "errors": [],
            "note": "no approved drafts pending publication",
        }

    dry_run = bool(args.get("dry_run", False))
    published: list[dict] = []
    errors: list[str] = []

    for d in drafts:
        try:
            result = _publish_one(conn, d, dry_run=dry_run)
            published.append(result)
        except Exception as e:
            errors.append(f"draft {d.get('id')}: {e}")

    if not dry_run:
        conn.commit()

    return {
        "drafts_published": len(published),
        "results": published[:10],
        "errors": errors[:10],
        "error_count": len(errors),
        "dry_run": dry_run,
    }


# Add WIKI_ROOT import path validation at module load — not required
# but catches misconfiguration early in dev.
assert isinstance(WIKI_ROOT, (str, Path)), "WIKI_ROOT must be a path-like"
