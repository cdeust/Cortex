"""Handler: wiki_adr — create a numbered ADR from structured fields.

Convenience wrapper around wiki_write: finds the next free ADR number,
renders the template via ``core.wiki_pages.build_adr``, and writes the
file. Registers the usual protected PG pointer memory.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_layout import adr_filename, page_path, slugify
from mcp_server.core.wiki_pages import ADR_STATUSES, build_adr
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import (
    WikiExists,
    next_adr_number,
    write_page,
)

schema = {
    "description": (
        "Create a numbered ADR (Architecture Decision Record) from "
        "structured Context/Decision/Consequences fields. Atomically: "
        "computes the next free ADR number, renders the standard template, "
        "writes wiki/adr/<NNNN>-<slug>.md under the wiki root, and "
        "registers a protected pointer memory tagged `wiki`+`adr` so the "
        "decision surfaces in `recall`. Use this whenever a non-trivial "
        "architectural choice is made — the resulting page is the single "
        "citable source of truth. Distinct from `wiki_write` (raw markdown, "
        "no auto-numbering, no template), and from `remember` (memory only, "
        "no .md file). Mutates the wiki/ tree and the memories table; "
        "refuses if the target file already exists. Latency ~50ms. Returns "
        "{path, number, title, status, created, bytes_written, root} or "
        "{error}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["title", "context", "decision", "consequences"],
        "properties": {
            "title": {
                "type": "string",
                "description": (
                    "Short imperative title of the decision. Will be slugified "
                    "into the filename. 5-80 characters recommended."
                ),
                "examples": [
                    "Use pgvector for ANN search",
                    "Adopt Clean Architecture layers",
                ],
            },
            "context": {
                "type": "string",
                "description": (
                    "The forces at play: what problem, what constraints, what "
                    "alternatives exist. Markdown allowed."
                ),
                "examples": [
                    "Recall latency exceeded 1s on 100k memories with cosine-only ranking."
                ],
            },
            "decision": {
                "type": "string",
                "description": (
                    "What was decided, in active voice. State the rule, not the discussion."
                ),
                "examples": [
                    "Adopt pgvector with HNSW index for first-stage ANN; FlashRank reranks top-N."
                ],
            },
            "consequences": {
                "type": "string",
                "description": (
                    "Resulting positive and negative consequences, including "
                    "what becomes easier and what becomes harder."
                ),
                "examples": [
                    "Postgres becomes mandatory; vector search ops are now server-side."
                ],
            },
            "status": {
                "type": "string",
                "description": (
                    "Lifecycle status of the ADR. Use 'proposed' during review, "
                    "'accepted' once shipped, 'superseded' when replaced (link "
                    "the new ADR)."
                ),
                "enum": list(ADR_STATUSES),
                "default": "accepted",
                "examples": ["proposed", "accepted"],
            },
            "tags": {
                "type": "array",
                "description": "Free-form tags for filtering and cross-referencing.",
                "items": {"type": "string"},
                "default": [],
                "examples": [["architecture", "storage"], ["retrieval", "embeddings"]],
            },
        },
    },
}


async def _store_pointer_memory(rel_path: str, content: str, tags: list[str]) -> None:
    try:
        from mcp_server.handlers import remember

        await remember.handler(
            {
                "content": content[:500],
                "tags": list({"wiki", "adr", *tags}),
                "source": f"wiki://{rel_path}",
                "force": True,
            }
        )
    except Exception:
        return


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    title = str(args.get("title") or "").strip()
    context = str(args.get("context") or "").strip()
    decision = str(args.get("decision") or "").strip()
    consequences = str(args.get("consequences") or "").strip()
    status = str(args.get("status") or "accepted")
    tags = [str(t) for t in (args.get("tags") or [])]

    if not title or not context or not decision or not consequences:
        return {"error": "title, context, decision and consequences are required"}
    if status not in ADR_STATUSES:
        return {"error": f"unknown status: {status}"}

    try:
        number = next_adr_number(WIKI_ROOT)
    except (ValueError, OSError) as exc:
        return {"error": f"cannot determine next ADR number: {exc}"}

    slug = slugify(title)
    filename = adr_filename(number, slug)
    rel_path = str(page_path("adr", filename))

    content = build_adr(
        number=number,
        title=title,
        context=context,
        decision=decision,
        consequences=consequences,
        status=status,
        tags=tags,
    )

    try:
        result = write_page(WIKI_ROOT, rel_path, content, mode="create")
    except WikiExists:
        return {"error": f"ADR already exists: {rel_path}"}
    except (ValueError, OSError) as exc:
        return {"error": f"write failed: {exc}"}

    await _store_pointer_memory(rel_path, content, tags)

    return {
        "path": result.path,
        "number": number,
        "title": title,
        "status": status,
        "created": result.created,
        "bytes_written": result.bytes_written,
        "root": str(WIKI_ROOT),
    }
