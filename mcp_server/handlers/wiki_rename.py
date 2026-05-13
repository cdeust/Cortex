"""Handler: wiki_rename — move a page and leave a redirect stub.

Phase 3.2 of ADR-2244. The operation:

  1. Read source page; require valid frontmatter ``id`` (Phase 3 invariant).
  2. Refuse if source is itself a redirect stub.
  3. Refuse if destination already exists (unless ``overwrite_dest`` true).
  4. Write source content at destination path.
  5. Replace source with a redirect stub pointing at destination (carrying
     the source's id-or-target id).

This is the building block for the Phase 4 bulk-rename script
(``.md.md`` cleanup, timestamp-slug fixes, ``file-*`` → ``files/``
moves). It is intentionally a small, well-tested handler that does one
move at a time; the bulk migration script will loop over it.

The two writes happen as best-effort sequential atomic writes. If the
destination write succeeds but the stub write fails, the caller sees an
error AND the page exists at both paths — investigated and reverted
manually. We do not roll back the destination write because that would
risk losing the new copy if the rollback itself fails. The bulk migration
script logs every move so any partial state is recoverable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcp_server.core.wiki_identity import extract_page_id, is_valid_page_id
from mcp_server.core.wiki_redirect import (
    build_redirect_stub,
    is_redirect,
    parse_frontmatter,
)
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import WikiExists, read_page, write_page


schema = {
    "title": "Wiki — rename page",
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Move a wiki page from ``from_path`` to ``to_path`` and leave a "
        "redirect stub at the old location pointing to the new one. "
        "Phase 3.2 of ADR-2244 — the move preserves inbound links because "
        "``wiki_read`` follows redirect stubs transparently. Refuses to "
        "operate on pages without a stable ``id`` field (run "
        "``scripts/wiki_backfill_ids.py`` first) or on existing redirect "
        "stubs. Returns {from_path, to_path, page_id, stub_created}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["from_path", "to_path"],
        "properties": {
            "from_path": {
                "type": "string",
                "description": "Current wiki-relative path of the page.",
                "examples": ["adr/_general/2234-decision-001-zero-dependencies.md.md"],
            },
            "to_path": {
                "type": "string",
                "description": "Destination wiki-relative path.",
                "examples": ["adr/_general/2234-zero-dependencies.md"],
            },
            "reason": {
                "type": "string",
                "description": (
                    "Optional free-form rationale recorded in the redirect "
                    "stub's frontmatter."
                ),
                "examples": [".md.md slug bug cleanup 2026-05-13"],
            },
            "overwrite_dest": {
                "type": "boolean",
                "description": (
                    "When true, overwrite an existing destination. Default "
                    "false — moves into occupied paths are an error."
                ),
                "default": False,
            },
        },
    },
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    from_path = str(args.get("from_path") or "").strip()
    to_path = str(args.get("to_path") or "").strip()
    reason = str(args.get("reason") or "").strip()
    overwrite_dest = bool(args.get("overwrite_dest", False))

    if not from_path:
        return {"error": "from_path is required"}
    if not to_path:
        return {"error": "to_path is required"}
    if from_path == to_path:
        return {"error": "from_path and to_path must differ"}

    # ── Read + validate source ────────────────────────────────────────
    try:
        source_content = read_page(WIKI_ROOT, from_path)
    except (ValueError, OSError) as exc:
        return {"error": f"source read failed: {exc}"}
    if source_content is None:
        return {"error": f"source page not found: {from_path}"}

    fm = parse_frontmatter(source_content)
    if is_redirect(fm):
        return {
            "error": (
                f"source is already a redirect stub: {from_path} — refusing "
                "to chain stubs (rename the terminal page instead)"
            )
        }
    page_id = extract_page_id(fm)
    if page_id is None:
        return {
            "error": (
                f"source page lacks a valid frontmatter id: {from_path}. "
                "Run scripts/wiki_backfill_ids.py --apply first."
            )
        }

    # ── Write destination ─────────────────────────────────────────────
    write_mode = "replace" if overwrite_dest else "create"
    try:
        write_page(WIKI_ROOT, to_path, source_content, mode=write_mode)
    except WikiExists:
        return {
            "error": (
                f"destination already exists: {to_path} — pass overwrite_dest "
                "to replace it"
            )
        }
    except (ValueError, OSError) as exc:
        return {"error": f"destination write failed: {exc}"}

    # ── Write redirect stub at source ────────────────────────────────
    # We use the (valid) page id from the source's frontmatter as the
    # ``redirect_id`` so id-based resolution works once the read-handler
    # supports it.
    stub = build_redirect_stub(
        target_path=to_path,
        target_id=page_id if is_valid_page_id(page_id) else None,
        target_title=str(fm.get("title", "")).strip(),
        reason=reason,
        created_at=_now_iso(),
    )
    try:
        write_page(WIKI_ROOT, from_path, stub, mode="replace")
    except (ValueError, OSError) as exc:
        return {
            "error": (
                f"stub write failed: {exc}; destination already written at "
                f"{to_path} — manual cleanup may be needed at {from_path}"
            ),
            "from_path": from_path,
            "to_path": to_path,
            "page_id": page_id,
            "stub_created": False,
        }

    return {
        "from_path": from_path,
        "to_path": to_path,
        "page_id": page_id,
        "stub_created": True,
    }
