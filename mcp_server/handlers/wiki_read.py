"""Handler: wiki_read — fetch the raw markdown of a wiki page.

Phase 3.2 of ADR-2244: when the page at the requested path is a redirect
stub, follow the chain transparently and return the target's content.
The response carries a ``redirect_chain`` array recording the paths
walked, so callers can detect and surface a "this page moved" hint to
their users when the caller cares.

Caller can opt out of redirect-following via ``follow_redirects: false``
to read the stub itself (useful for admin / migration tooling that
needs to inspect or rewrite the stub).

T2-H4/INC5.4 (D7): page content is filesystem-only, unchanged. On a
successful read this handler ALSO records a best-effort wiki.citations
row for the page actually returned to the caller — the schema's own
comment names citations "the primary authority-earning signal"
(pg_schema.py) and the write-path was dormant (``insert_citation`` had
zero callers) until session identity became available via the T2
window-session registry. This is a deliberate, explicit side effect,
not a violation of "read-only": the markdown read and its result never
depend on PG being reachable — see ``_cite_page``'s contract below.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.response_budget import TextTarget, bound_payload
from mcp_server.core.wiki_redirect import (
    MAX_REDIRECT_DEPTH,
    parse_frontmatter,
    parse_redirect,
    resolve_chain,
)
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.pg_store_wiki import (
    get_page_by_rel_path,
    insert_citation,
)
from mcp_server.infrastructure.session_registry import current_window_session
from mcp_server.infrastructure.wiki_store import read_page

logger = logging.getLogger(__name__)

schema = {
    "title": "Wiki — read page",
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Fetch the raw markdown source of one wiki page by its wiki-relative "
        "path. Path resolution is sandboxed under the wiki root — absolute "
        "paths and `../` traversal are rejected at the storage layer. When "
        "the page is a redirect stub (frontmatter ``redirect_to:`` or "
        "``redirect_id:``) the chain is followed transparently up to "
        f"{MAX_REDIRECT_DEPTH} hops; cycles and dangling targets surface as "
        "errors. Pass ``follow_redirects: false`` to read the stub itself. "
        "Page content is filesystem-only and always returned even if "
        "PostgreSQL is unreachable. As an explicit side effect, a "
        "successful read within a known Claude Code session records one "
        "deduplicated wiki.citations row (page, session) — the primary "
        "authority-earning signal driving page heat/citation_count; "
        "best-effort, never blocks or fails the read (no window session, "
        "PG down, or a page never compiled into PG all degrade to 'read "
        "succeeds, no citation'). Distinct from `wiki_list` which "
        "enumerates available pages, and from `wiki_export` which renders a "
        "page through Pandoc to PDF/DOCX/HTML. Latency <10ms. Returns "
        "{path, content, content_length, offset, root, redirect_chain} or "
        "{error}. Pages larger than the response budget come back with "
        "``content_truncated: true`` — page via the ``offset`` argument."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Wiki-relative path of the page to read (no leading "
                    "slash, no `..`). Must end in .md and resolve under the "
                    "wiki root."
                ),
                "examples": [
                    "adr/0042-pgvector.md",
                    "concepts/wrrf-fusion.md",
                    "specs/cortex/recall-pipeline.md",
                ],
            },
            "follow_redirects": {
                "type": "boolean",
                "description": (
                    "When true (default) redirect stubs are followed "
                    "transparently. When false the stub itself is returned, "
                    "which is useful for admin / migration tooling."
                ),
                "default": True,
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Start the returned content at this character offset. "
                    "Page through pages larger than the response budget: "
                    "when the response carries ``content_truncated: true``, "
                    "re-call with offset = previous offset + length of the "
                    "content received. ``content_length`` is the full page "
                    "size."
                ),
                "default": 0,
                "minimum": 0,
            },
        },
    },
}


def _bounded(resp: dict[str, Any], offset: int) -> dict[str, Any]:
    """Slice content at ``offset`` and fit the response to the budget.

    ``content_length`` always carries the full page size so callers can
    page; ``content_truncated`` appears when the slice was cut (set by
    bound_payload, core/response_budget.py).
    """
    content = resp.get("content") or ""
    resp["content_length"] = len(content)
    resp["offset"] = offset
    if offset > 0:
        resp["content"] = content[offset:]
    return bound_payload(
        resp, [TextTarget("content")], get_memory_settings().MAX_RESPONSE_CHARS
    )


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


def _resolve_session_id() -> str | None:
    """Best-effort session-identity lookup (T2-H4, mirrors recall.py's
    ``_resolve_session_id`` — same registry, same degradation mode: the
    registry's own contract never raises by construction, but the read
    path must not depend on that holding forever).
    """
    try:
        return current_window_session()
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("session registry lookup failed", exc_info=True)
        return None


def _cite_page(rel_path: str) -> None:
    """Record a wiki.citations row for the page actually returned, best-effort.

    precondition: rel_path is the wiki-relative path of the page whose
    content was returned to the caller (post-redirect-resolution — the
    terminal page, not the stub).
    postcondition: iff a window session is resolvable AND rel_path
    resolves to a compiled wiki.pages row, exactly one new
    wiki.citations row exists for (page_id, session_id) unless one
    already existed for this session (dedup is enforced DB-side by
    ``insert_citation``/``uq_wiki_citations_page_session`` — T2-D12/D7/
    Q2 arbitrage: a citation without session identity has no CITED_IN
    semantics and must not be recorded at all, so no session_id means
    no citation, full stop). On every other outcome (no session, PG
    unreachable, store not PG-backed, page never compiled into PG, or
    any other exception) this is a silent no-op — wiki_read's
    filesystem read has already succeeded by the time this runs and
    must never be affected by this observability side channel.
    """
    session_id = _resolve_session_id()
    if not session_id:
        return
    try:
        store = _get_store()
        conn = store._conn
        page = get_page_by_rel_path(conn, rel_path)
        if page is None:
            return
        insert_citation(
            conn,
            page_id=page["id"],
            session_id=session_id,
            domain=page.get("domain", ""),
            memory_id=page.get("memory_id"),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug(
            "wiki_read citation side-effect failed for %s", rel_path, exc_info=True
        )


def _frontmatter_reader(rel_path: str) -> dict[str, object]:
    """Read a page's frontmatter from disk via the sandboxed store.

    Returns an empty dict for missing or unreadable pages — that matches
    the ``parse_redirect`` contract (no redirect = no decoration).
    """
    try:
        content = read_page(WIKI_ROOT, rel_path)
    except (ValueError, OSError):
        return {}
    if content is None:
        return {}
    return parse_frontmatter(content)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    rel_path = str(args.get("path") or "").strip()
    if not rel_path:
        return {"error": "path is required"}
    follow = bool(args.get("follow_redirects", True))
    offset = max(0, int(args.get("offset") or 0))

    try:
        content = read_page(WIKI_ROOT, rel_path)
    except (ValueError, OSError) as exc:
        return {"error": f"read failed: {exc}"}
    if content is None:
        return {"error": f"page not found: {rel_path}"}

    # Fast path: caller wants the stub itself, or the page isn't a stub.
    if not follow:
        _cite_page(rel_path)
        return _bounded(
            {
                "path": rel_path,
                "content": content,
                "root": str(WIKI_ROOT),
                "redirect_chain": [],
            },
            offset,
        )

    fm = parse_frontmatter(content)
    if parse_redirect(fm) is None:
        _cite_page(rel_path)
        return _bounded(
            {
                "path": rel_path,
                "content": content,
                "root": str(WIKI_ROOT),
                "redirect_chain": [],
            },
            offset,
        )

    # Stub — walk the chain to the terminal page.
    resolved = resolve_chain(rel_path, _frontmatter_reader)
    if resolved is None:
        return {
            "error": (
                f"redirect chain from {rel_path} could not be resolved "
                f"(cycle, depth > {MAX_REDIRECT_DEPTH}, or id-only redirect "
                f"without a path)"
            ),
            "path": rel_path,
        }

    try:
        target_content = read_page(WIKI_ROOT, resolved.final_path)
    except (ValueError, OSError) as exc:
        return {"error": f"redirect target read failed: {exc}"}
    if target_content is None:
        return {
            "error": (
                f"redirect chain from {rel_path} terminates at "
                f"{resolved.final_path}, but that page no longer exists"
            ),
            "redirect_chain": list(resolved.chain),
        }

    _cite_page(resolved.final_path)
    return _bounded(
        {
            "path": resolved.final_path,
            "content": target_content,
            "root": str(WIKI_ROOT),
            "redirect_chain": list(resolved.chain),
        },
        offset,
    )
