"""wiki.drafts DB operations.

Split out of ``pg_store_wiki.py`` (originally 890 lines, over the
300-line file limit — CLAUDE.md "Code Quality Rules") purely for size
compliance; no logic changed.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from typing_extensions import LiteralString
    from mcp_server.infrastructure.db_types import StoreConnection

import json


from mcp_server.infrastructure.pg_store_wiki_common import _returning_id


def insert_draft(conn: StoreConnection, draft: dict[str, Any]) -> int:
    """Insert a draft row. Returns the new wiki.drafts.id.

    Required: title, kind. Optional: concept_id, memory_id, lead,
    sections (list of dicts), frontmatter, provenance, synth_prompt,
    synth_model, confidence, status.
    """
    sql = """
    INSERT INTO wiki.drafts (
        concept_id, memory_id, title, kind, lead, sections,
        frontmatter, provenance, synth_prompt, synth_model,
        confidence, status
    ) VALUES (
        %(concept_id)s, %(memory_id)s, %(title)s, %(kind)s, %(lead)s,
        %(sections)s::jsonb, %(frontmatter)s::jsonb,
        %(provenance)s::jsonb, %(synth_prompt)s, %(synth_model)s,
        %(confidence)s, %(status)s
    ) RETURNING id;
    """
    params = {
        "concept_id": draft.get("concept_id"),
        "memory_id": draft.get("memory_id"),
        "title": draft["title"],
        "kind": draft["kind"],
        "lead": draft.get("lead", ""),
        "sections": json.dumps(draft.get("sections", [])),
        "frontmatter": json.dumps(draft.get("frontmatter", {})),
        "provenance": json.dumps(draft.get("provenance", {})),
        "synth_prompt": draft.get("synth_prompt"),
        "synth_model": draft.get("synth_model"),
        "confidence": float(draft.get("confidence", 0.5)),
        "status": draft.get("status", "pending"),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return _returning_id(cur.fetchone())


def get_draft(conn: StoreConnection, draft_id: int) -> dict | None:
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM wiki.drafts WHERE id = %s", (draft_id,))
        return cur.fetchone()


def list_drafts(
    conn: StoreConnection,
    *,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> list[dict]:
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    where: list[str] = []
    params: list = []
    if status:
        where.append("status = %s")
        params.append(status)
    if kind:
        where.append("kind = %s")
        params.append(kind)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
    SELECT * FROM wiki.drafts {where_sql}
    ORDER BY created_at DESC LIMIT %s
    """  # noqa: S608 — WHERE built from in-code literal fragments; values are bound parameters (docs/ASSURANCE-CASE.md §5)
    params.append(limit)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(cast("LiteralString", sql), params)
        return list(cur.fetchall())


def update_draft(
    conn: StoreConnection,
    draft_id: int,
    *,
    title: str | None = None,
    lead: str | None = None,
    sections: list | None = None,
    frontmatter: dict | None = None,
    confidence: float | None = None,
    synth_prompt: str | None = None,
    synth_model: str | None = None,
) -> bool:
    """Patch a draft's content fields. Returns True if a row was updated.

    Used by Path B (LLM refinement) — Claude submits a refined draft
    by updating the in-DB record. Status transitions go through
    update_draft_status.
    """
    sets: list[str] = []
    params: list = []
    if title is not None:
        sets.append("title = %s")
        params.append(title)
    if lead is not None:
        sets.append("lead = %s")
        params.append(lead)
    if sections is not None:
        sets.append("sections = %s::jsonb")
        params.append(json.dumps(sections))
    if frontmatter is not None:
        sets.append("frontmatter = %s::jsonb")
        params.append(json.dumps(frontmatter))
    if confidence is not None:
        sets.append("confidence = %s")
        params.append(float(confidence))
    if synth_prompt is not None:
        sets.append("synth_prompt = %s")
        params.append(synth_prompt)
    if synth_model is not None:
        sets.append("synth_model = %s")
        params.append(synth_model)
    if not sets:
        return False
    params.append(draft_id)
    sql = f"UPDATE wiki.drafts SET {', '.join(sets)} WHERE id = %s"  # noqa: S608 — SET fragments are in-code literals appended per known field; values are bound parameters (docs/ASSURANCE-CASE.md §5)
    with conn.cursor() as cur:
        cur.execute(cast("LiteralString", sql), params)
        return cur.rowcount > 0


def update_draft_status(
    conn: StoreConnection,
    draft_id: int,
    *,
    status: str,
    published_page_id: int | None = None,
) -> bool:
    """Transition a draft's status. Stamps reviewed_at automatically."""
    if status not in ("pending", "approved", "rejected", "published"):
        raise ValueError(f"invalid status: {status}")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE wiki.drafts
               SET status = %s,
                   published_page_id = COALESCE(%s, published_page_id),
                   reviewed_at = NOW()
             WHERE id = %s
            """,
            (status, published_page_id, draft_id),
        )
        return cur.rowcount > 0


def find_draft_for_source(
    conn: StoreConnection,
    *,
    memory_id: int | None = None,
    concept_id: int | None = None,
) -> dict | None:
    """Return the most recent draft for a given source, or None."""
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    if not memory_id and not concept_id:
        return None
    if memory_id is not None:
        sql = (
            "SELECT * FROM wiki.drafts WHERE memory_id = %s "
            "ORDER BY created_at DESC LIMIT 1"
        )
        params: tuple = (memory_id,)
    else:
        sql = (
            "SELECT * FROM wiki.drafts WHERE concept_id = %s "
            "ORDER BY created_at DESC LIMIT 1"
        )
        params = (concept_id,)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchone()
