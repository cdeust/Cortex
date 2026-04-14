"""Wiki API handlers for the visualization HTTP server.

Filesystem-backed endpoints (unchanged since Phase 1):
  /api/wiki/list   — enumerate .md files
  /api/wiki/page   — read one .md file

DB-backed endpoints (Phase 6 — expose the redesigned layers):
  /api/wiki/page_meta  — thermo state + citations + backlinks for one page
  /api/wiki/concepts   — list candidate/saturating/promoted concepts
  /api/wiki/drafts     — list drafts, filter by status/kind
  /api/wiki/memos      — audit trail for a subject (page/draft/concept/claim)
  /api/wiki/views      — list available views
  /api/wiki/view       — execute a view by name

All DB endpoints gracefully return empty results if the wiki.* schema
isn't populated yet. Never raises — errors become {"error": "..."}.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

from mcp_server.core.wiki_pages import parse_page
from mcp_server.core.wiki_view_executor import compile_view
from mcp_server.infrastructure.wiki_store import list_pages, read_page


def list_wiki_pages(wiki_root: Path) -> list[dict]:
    """List all wiki pages with parsed frontmatter metadata."""
    pages = list_pages(wiki_root)
    result = []
    for rel_path in pages:
        content = read_page(wiki_root, rel_path)
        if content is None:
            continue
        doc = parse_page(content)
        fm = doc.frontmatter
        stem = Path(rel_path).stem
        result.append(
            {
                "path": rel_path,
                "title": fm.get("title", stem),
                "kind": fm.get("kind", ""),
                "domain": fm.get("domain", ""),
                "maturity": fm.get("maturity", ""),
                "tags": fm.get("tags", []),
                "created": str(fm.get("created", "")),
                "updated": str(fm.get("updated", "")),
            }
        )
    return result


def read_wiki_page(wiki_root: Path, rel_path: str) -> dict:
    """Read a single wiki page with metadata and body."""
    if "/../" in rel_path or rel_path.startswith("../") or "\x00" in rel_path:
        return {"error": "invalid path"}
    content = read_page(wiki_root, rel_path)
    if content is None:
        return {"error": "not found", "path": rel_path}
    doc = parse_page(content)
    return {
        "path": rel_path,
        "meta": doc.frontmatter,
        "body": doc.body,
    }


# ── DB-backed endpoints (Phase 6) ─────────────────────────────────────


def _get_store():
    """Lazy store accessor — never raises; returns None if DB missing."""
    try:
        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import MemoryStore

        settings = get_memory_settings()
        return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    except Exception:
        return None


def _rows_to_plain(rows: list[Any]) -> list[dict]:
    """Coerce psycopg rows to plain JSON-serialisable dicts."""
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            clean = {}
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    clean[k] = v.isoformat()
                elif isinstance(v, (bytes, bytearray)):
                    clean[k] = v.hex()
                else:
                    clean[k] = v
            out.append(clean)
    return out


def page_meta(rel_path: str) -> dict:
    """Return thermodynamic state + links + recent citations for one page.

    Input is the same rel_path used by read_wiki_page. DB lookup by
    rel_path joins against wiki.links and wiki.citations.
    """
    if not rel_path or "/../" in rel_path or rel_path.startswith("../"):
        return {"error": "invalid path"}
    store = _get_store()
    if store is None:
        return {"error": "db unavailable"}
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, title, kind, domain, status, lifecycle_state,
                   heat, access_count, citation_count, backlink_count,
                   is_stale, planted, tended, last_cited_at, archived_at,
                   memory_id, concept_id
              FROM wiki.pages
             WHERE rel_path = %s
             LIMIT 1
            """,
            (rel_path,),
        )
        page = cur.fetchone()
    if page is None:
        return {"rel_path": rel_path, "db_row": None}

    page_id = page["id"]
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT src_page_id, dst_slug, dst_page_id, link_kind,
                   (SELECT title FROM wiki.pages WHERE id = l.src_page_id) AS src_title,
                   (SELECT rel_path FROM wiki.pages WHERE id = l.src_page_id) AS src_rel_path
              FROM wiki.links l
             WHERE dst_page_id = %s
             LIMIT 100
            """,
            (page_id,),
        )
        backlinks = _rows_to_plain(list(cur.fetchall()))
        cur.execute(
            """
            SELECT dst_slug, dst_page_id, link_kind
              FROM wiki.links WHERE src_page_id = %s LIMIT 100
            """,
            (page_id,),
        )
        out_links = _rows_to_plain(list(cur.fetchall()))
        cur.execute(
            """
            SELECT id, session_id, domain, memory_id, cited_at
              FROM wiki.citations
             WHERE page_id = %s ORDER BY cited_at DESC LIMIT 20
            """,
            (page_id,),
        )
        citations = _rows_to_plain(list(cur.fetchall()))

    return {
        "rel_path": rel_path,
        "db_row": _rows_to_plain([page])[0],
        "backlinks": backlinks,
        "outbound_links": out_links,
        "recent_citations": citations,
    }


def list_concepts(status: str | None = None, limit: int = 100) -> dict:
    store = _get_store()
    if store is None:
        return {"error": "db unavailable", "concepts": []}
    sql = (
        "SELECT id, label, status, saturation_streak, "
        "array_length(entity_ids, 1) AS n_entities, "
        "array_length(grounding_memory_ids, 1) AS n_memories, "
        "array_length(grounding_claim_ids, 1) AS n_claims, "
        "promoted_page_id "
        "FROM wiki.concepts"
    )
    params: list = []
    if status:
        sql += " WHERE status = %s"
        params.append(status)
    sql += " ORDER BY saturation_streak DESC NULLS LAST, id DESC LIMIT %s"
    params.append(limit)
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = _rows_to_plain(list(cur.fetchall()))
    return {"concepts": rows, "count": len(rows)}


def list_drafts(
    status: str | None = None, kind: str | None = None, limit: int = 100
) -> dict:
    store = _get_store()
    if store is None:
        return {"error": "db unavailable", "drafts": []}
    where: list[str] = []
    params: list = []
    if status:
        where.append("status = %s")
        params.append(status)
    if kind:
        where.append("kind = %s")
        params.append(kind)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, concept_id, memory_id, kind, title, status, "
        "confidence, synth_model, created_at, reviewed_at, published_page_id "
        f"FROM wiki.drafts{where_sql} "
        "ORDER BY created_at DESC LIMIT %s"
    )
    params.append(limit)
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = _rows_to_plain(list(cur.fetchall()))
    return {"drafts": rows, "count": len(rows)}


def list_memos(subject_type: str, subject_id: int, limit: int = 50) -> dict:
    if subject_type not in ("page", "concept", "draft", "claim"):
        return {"error": f"invalid subject_type: {subject_type!r}", "memos": []}
    store = _get_store()
    if store is None:
        return {"error": "db unavailable", "memos": []}
    with store._conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, decision, rationale, confidence, author, created_at,
                   inputs
              FROM wiki.memos
             WHERE subject_type = %s AND subject_id = %s
             ORDER BY created_at DESC LIMIT %s
            """,
            (subject_type, subject_id, limit),
        )
        rows = _rows_to_plain(list(cur.fetchall()))
    return {"memos": rows, "count": len(rows)}


def list_views() -> dict:
    """Views live in wiki/_views/*.md; loader handles them."""
    try:
        from mcp_server.core.wiki_schema_loader import load_registry
        from mcp_server.infrastructure.config import WIKI_ROOT

        registry = load_registry(Path(WIKI_ROOT))
    except Exception as e:
        return {"error": str(e), "views": []}
    return {
        "views": [
            {
                "name": v.name,
                "rel_path": v.rel_path,
                "description": v.description,
            }
            for v in registry.views.values()
        ],
        "count": len(registry.views),
    }


def execute_view(name: str | None, inline_query: str | None = None) -> dict:
    """Execute a named view or an inline cortex-query block."""
    try:
        from mcp_server.core.wiki_schema_loader import load_registry
        from mcp_server.infrastructure.config import WIKI_ROOT
    except Exception as e:
        return {"error": f"config error: {e}"}

    if name:
        try:
            registry = load_registry(Path(WIKI_ROOT))
        except Exception as e:
            return {"error": f"registry load failed: {e}"}
        view = registry.views.get(name)
        if view is None:
            return {
                "error": f"view {name!r} not found",
                "available": list(registry.views.keys()),
            }
        query_text = view.query
        view_meta = {"name": view.name, "rel_path": view.rel_path}
    elif inline_query:
        query_text = inline_query
        view_meta = {"name": "<inline>", "rel_path": None}
    else:
        return {"error": "name or query is required"}

    compiled = compile_view(query_text)
    if not compiled.ok:
        return {
            "view": view_meta,
            "error": "compile failed",
            "errors": compiled.errors,
        }

    store = _get_store()
    if store is None:
        return {"view": view_meta, "error": "db unavailable"}
    with store._conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute(compiled.sql, compiled.params)
            rows = _rows_to_plain(list(cur.fetchall()))
        except Exception as e:
            return {"view": view_meta, "error": f"execution failed: {e}"}

    return {
        "view": view_meta,
        "table": compiled.table,
        "row_count": len(rows),
        "rows": rows,
    }


__all__ = [
    "list_wiki_pages",
    "read_wiki_page",
    "page_meta",
    "list_concepts",
    "list_drafts",
    "list_memos",
    "list_views",
    "execute_view",
]
