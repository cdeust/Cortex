"""Handler: wiki_write — author a new wiki page or update an existing one.

Composition root for the authoring path. Renders templated content via
``core.wiki_pages`` when a ``kind`` is supplied, then delegates the
atomic write to ``infrastructure.wiki_store``. After a successful write,
stores a protected PG pointer memory tagged ``wiki`` so ``recall`` can
surface the page like any other memory.

I6-D7/INC6.8 ("flux avant" citations): this is the completion handler
for ``curate_wiki``'s authoring jobs — the in-session LLM reads a job's
``memory_ids``/``supporting_memory_ids``, decides which of them it
actually used while authoring, and passes THAT subset back here via
``memory_ids``. Two additional best-effort side effects fire after a
successful write, mirroring ``wiki_read``'s ``_cite_page`` contract
(same degrade-to-no-op discipline, same "the write already succeeded
on disk, this is pure observability" boundary):

  1. Sync the page into ``wiki.pages`` synchronously (reuses
     ``wiki_migrate.page_row_from_md`` + ``upsert_page`` — the same
     row-shape ``wiki_migrate``'s batch sweep would produce later).
     Without this, ``wiki.citations`` would have no ``page_id`` to
     attach to until the next migration sweep ran.
  2. If ``memory_ids`` was passed, insert one ``wiki.citations`` row
     per memory_id — dedup key is ``(page_id, memory_id)``, distinct
     from ``wiki_read``'s ``(page_id, session_id)`` key (see
     ``insert_citation``'s docstring, pg_store_wiki_notes.py).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp_server.core.prose_redaction import scan_prose, summarize_findings
from mcp_server.core.wiki_frontmatter_validation import UnclosedFrontmatterError
from mcp_server.core.wiki_layout import page_path
from mcp_server.core.wiki_pages import (
    build_adr,
    build_file_doc,
    build_note,
    build_spec,
)
from mcp_server.handlers.wiki_migrate import page_row_from_md
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.pg_store_wiki import insert_citation, upsert_page
from mcp_server.infrastructure.session_registry import current_window_session
from mcp_server.infrastructure.wiki_store import (
    WikiExists,
    WikiMissing,
    write_page,
)

from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)

schema = {
    "title": "Wiki — write page",
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Author a new wiki page or append/replace content on an existing "
        "one (kind inferred from the first path segment: adr, specs, "
        "files, notes, lessons, conventions, guides, reference, journal). "
        "Pages live under ~/.claude/methodology/wiki/, written atomically "
        "via tmp+rename. After a successful write, registers a protected "
        "PG pointer memory tagged `wiki` so the page surfaces in `recall`. "
        "Use this for any document that should outlive the session — "
        "lessons, conventions, runbooks, anything you might link from a "
        "future ADR. Distinct from `wiki_adr` (auto-numbered ADRs from "
        "structured Context/Decision/Consequences), `wiki_compile` "
        "(publishes already-curated drafts), and `remember` (no markdown "
        "page, just a memory). Mutates the wiki/ tree, the memories "
        "table, wiki.pages (synced synchronously so the page has a "
        "resolvable id immediately), and — when `memory_ids` is passed "
        "— wiki.citations (one deduplicated row per memory actually used "
        "to author the page; how a curate_wiki job's memory cluster "
        "becomes durable, queryable provenance). Latency ~50ms. Returns "
        "{path, mode, created, bytes_written, root, citations_written} "
        "or {error}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Wiki-relative path of the page (no leading slash). The "
                    "first path segment determines the page kind."
                ),
                "examples": ["notes/recall-regression.md", "lessons/dont-mock-db.md"],
            },
            "content": {
                "type": "string",
                "description": (
                    "Raw markdown content. Used when structured fields "
                    "(title/summary/body) are not provided. Markdown is preserved verbatim."
                ),
            },
            "mode": {
                "type": "string",
                "description": (
                    "Write mode. 'create' refuses if the page exists; "
                    "'append' adds to the bottom; 'replace' overwrites."
                ),
                "enum": ["create", "append", "replace"],
                "default": "create",
                "examples": ["create", "append"],
            },
            "title": {
                "type": "string",
                "description": "Page title (used when rendering from template).",
                "examples": ["Recall regression triaged 2026-04-12"],
            },
            "summary": {
                "type": "string",
                "description": "One-paragraph summary placed near the top of the rendered page.",
                "examples": ["FlashRank ONNX cache divergence; clearing fixed it."],
            },
            "body": {
                "type": "string",
                "description": "Main markdown body inserted into the template.",
            },
            "tags": {
                "type": "array",
                "description": "Free-form tags attached to both the wiki frontmatter and the pointer memory.",
                "items": {"type": "string"},
                "default": [],
                "examples": [["lesson", "recall"], ["adr", "embeddings"]],
            },
            "memory_ids": {
                "type": "array",
                "description": (
                    "IDs of the memories you actually drew on while "
                    "authoring this content — typically a subset of a "
                    "`curate_wiki` job's `memory_ids`/"
                    "`supporting_memory_ids` (a job proposes candidates; "
                    "you may not have used all of them). Recorded as one "
                    "deduplicated wiki.citations row per id, best-effort — "
                    "never blocks or fails the write. Omit if this page "
                    "wasn't authored from a curate_wiki job."
                ),
                "items": {"type": "integer"},
                "default": [],
                "examples": [[10234, 10240, 10256]],
            },
        },
    },
}


async def _store_pointer_memory(rel_path: str, content: str, tags: list[str]) -> None:
    """Best-effort: register a protected pointer memory for recall."""
    try:
        from mcp_server.handlers import remember

        await remember.handler(
            {
                "content": content[:500],
                "tags": list({"wiki", *tags}),
                "source": f"wiki://{rel_path}",
                # M-D2 (7.4): structural indexing bookkeeping (a protected
                # pointer memory for recall), not user-authored content.
                "write_class": "mechanical",
                "force": True,
            }
        )
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("wiki_write.pointer_memory", exc)
        return


def _sync_page_and_cite(rel_path: str, content: str, memory_ids: list[int]) -> int:
    """Sync ``wiki.pages`` and record citations for the memories used, best-effort.

    precondition: rel_path/content are the page just written to disk by
    ``write_page`` (already succeeded by the time this runs).
    postcondition: on success, exactly one wiki.pages row exists for
    rel_path (inserted or refreshed by ``page_row_from_md`` +
    ``upsert_page`` — same shape ``wiki_migrate``'s batch sweep would
    produce) and, for each id in ``memory_ids``, at most one new
    wiki.citations row exists keyed on (page_id, memory_id) — a repeat
    id (this call or a prior one) is a silent DB-level no-op, never an
    error (``insert_citation``'s unqualified ON CONFLICT DO NOTHING).
    Unlike wiki_read's ``_cite_page``, a resolvable window session is
    NOT required: this citation records "memory used to author the
    page", not "page read in this session" — the two are orthogonal
    provenance signals sharing one table. session_id falls back to ''
    (the column's own NOT NULL DEFAULT) when no window session is
    resolvable, matching the schema rather than skipping the row.
    On ANY exception (PG down, store not PG-backed, etc.) this
    degrades to a no-op — the markdown write already succeeded and
    must never be affected by this observability side channel.
    Returns the number of new citation rows written (0 on any failure
    or when memory_ids is empty).
    """
    try:
        settings = get_memory_settings()
        store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
        conn = store._conn
        page_row = page_row_from_md(rel_path, content)
        page_id, _was_modified = upsert_page(conn, page_row)
        if page_id is None or page_id < 0 or not memory_ids:
            conn.commit()
            return 0
        try:
            session_id = current_window_session() or ""
        except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
            silent_failure.note("wiki_write.session_lookup", exc)
            session_id = ""
        written = 0
        for mid in memory_ids:
            new_id = insert_citation(
                conn,
                page_id=page_id,
                session_id=session_id,
                domain=page_row.get("domain", ""),
                memory_id=mid,
            )
            if new_id is not None:
                written += 1
        conn.commit()
        return written
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug(
            "wiki_write page-sync/citation side-effect failed for %s",
            rel_path,
            exc_info=True,
        )
        return 0


async def write_governed_page(
    root: Path | str,
    rel_path: str,
    content: str,
    *,
    mode: str = "create",
    tags: list[str] | None = None,
    memory_ids: list[int] | None = None,
) -> dict[str, Any]:
    """The governed wiki-write path — adds pointer-memory + citation
    bookkeeping on top of a plain ``write_page`` call.

    precondition: ``root`` is a wiki root (production ``WIKI_ROOT`` or, for a
    caller operating on an alternate tree such as a test fixture, that
    tree's own root); ``rel_path`` is root-relative; ``content`` is the full
    markdown (frontmatter + body) to persist.
    postcondition: write-time frontmatter normalization (issue #107) is
    enforced by ``write_page`` itself (issue #110 — the choke point moved
    down to ``infrastructure.wiki_store`` so it covers every caller, not
    just this one), so this function no longer needs to (and does not)
    call ``normalize_frontmatter`` a second time. On success, the page is
    written atomically (tmp+rename, ``write_page``'s existing guarantee)
    AND a protected ``write_class='mechanical'`` pointer memory is stored
    via ``remember`` (best-effort — never blocks or fails the write;
    mechanical is correct per remember_schema.py's own vocabulary:
    "structural indexing — ... wiki pointer sync — bypasses the gate
    entirely, force=true semantics"; this call stores a 500-char pointer,
    not the full authored content, so the class describes the
    pointer-write, not who authored the page body) AND
    ``wiki.pages``/``wiki.citations`` are synced best-effort (same
    degrade-to-no-op discipline as ``_sync_page_and_cite``'s own contract).
    Write-time provenance grading (``INC7.5`` — ``grade_from_content``,
    triggered inside ``remember()``'s insert path) fires automatically as a
    consequence of routing through here; no separate grading call is needed.
    Returns ``{path, mode, created, bytes_written, root, citations_written}``
    or ``{error}``.

    This is the ONLY function in the codebase that may register the
    pointer-memory + citations governance side effects — the interactive
    ``wiki_write`` MCP tool (``handler``, below) and the headless
    authoring worker (``consolidation/page_io.py``) both route through
    here so no caller performing an authored, citable write skips that
    bookkeeping. It is emphatically NOT the only caller of ``write_page``:
    several handlers (redirect stubs, generated reference/PRD/finding
    pages, ADRs, links) call ``write_page`` directly because pointer
    memories and citations do not apply to their output — see
    ``tests_py/architecture/test_write_page_call_sites.py`` for the
    audited whitelist that guards against a new, unreviewed direct
    caller appearing silently. Frontmatter normalization is unconditional
    for all of them regardless (see ``write_page``'s own contract).

    raises: ``UnclosedFrontmatterError`` (propagated, uncaught, from
    ``write_page``'s call to ``normalize_frontmatter``) when ``content``
    opens a frontmatter fence it never closes — the one shape that is
    structurally inexploitable. The interactive tool call (``handler``,
    below, registered via ``safe_handler``) turns this into a
    ``fastmcp.exceptions.ToolError`` automatically (the repo's standing
    idiom — see commits c7dfc243/49f29e98); ``consolidation/page_io.py``'s
    non-tool callers catch it explicitly and degrade to their existing
    failure contract.
    """
    try:
        result = write_page(root, rel_path, content, mode=mode)
    except WikiExists:
        return {"error": f"page already exists: {rel_path}"}
    except WikiMissing:
        return {"error": f"page does not exist: {rel_path}"}
    except UnclosedFrontmatterError:
        # Propagate uncaught (see docstring) — narrower than the ValueError
        # catch below, which must not swallow this one. write_page now
        # raises it from its own normalize_frontmatter call (issue #110
        # moved that call down from this function).
        raise
    except (ValueError, OSError) as exc:
        return {"error": f"write failed: {exc}"}

    await _store_pointer_memory(rel_path, content, tags or [])

    citations_written = _sync_page_and_cite(rel_path, content, memory_ids or [])

    # Advisory prose measurement (issue #166): generated pages carry an
    # AI-writing-tell report so authoring quality is visible at write time.
    # Never blocks the write; empty report is omitted to keep responses lean.
    findings = scan_prose(content)
    response: dict[str, Any] = {
        "path": result.path,
        "mode": result.mode,
        "created": result.created,
        "bytes_written": result.bytes_written,
        "root": str(root),
        "citations_written": citations_written,
    }
    if findings:
        response["redaction_findings"] = summarize_findings(findings)
    return response


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    rel_path = str(args.get("path") or "").strip()
    if not rel_path:
        return {"error": "path is required"}
    mode = str(args.get("mode") or "create")
    content = args.get("content")

    if not content:
        return {
            "error": (
                "content is required — render the page yourself "
                "(e.g. via wiki_adr for ADRs) and pass the final markdown."
            )
        }

    tags = [str(t) for t in (args.get("tags") or [])]
    memory_ids = [int(m) for m in (args.get("memory_ids") or [])]

    return await write_governed_page(
        WIKI_ROOT,
        rel_path,
        str(content),
        mode=mode,
        tags=tags,
        memory_ids=memory_ids,
    )


__all__ = [
    "handler",
    "schema",
    "page_path",
    "build_adr",
    "build_spec",
    "build_file_doc",
    "build_note",
    "write_governed_page",
]
