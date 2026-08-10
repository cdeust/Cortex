"""Tool registration: wiki authoring tools (10 tools).

Registers the authoring surface that lets Claude maintain a first-class
Markdown wiki (ADRs, specs, file docs, notes) alongside PostgreSQL
memory. Pages are never derived from PG — they are authored via these
tools and indexed in PG as protected pointer memories for recall.
``wiki_migrate`` is the exception: it is the one-shot FS->PG sync +
ghost-reconciliation job (see ``mcp_server.handlers.wiki_migrate``),
exposed here so parity can be re-run and inspected without a shell.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_server.handlers import (
    wiki_adr,
    wiki_link,
    wiki_list,
    wiki_migrate,
    wiki_purge,
    wiki_read,
    wiki_reindex,
    wiki_rename,
    wiki_verify,
    wiki_write,
)
from mcp_server.handlers._tool_meta import tool_kwargs
from mcp_server.tool_error_handler import safe_handler


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "wiki_adr": wiki_adr.schema,
    "wiki_link": wiki_link.schema,
    "wiki_list": wiki_list.schema,
    "wiki_migrate": wiki_migrate.schema,
    "wiki_purge": wiki_purge.schema,
    "wiki_read": wiki_read.schema,
    "wiki_reindex": wiki_reindex.schema,
    "wiki_rename": wiki_rename.schema,
    "wiki_verify": wiki_verify.schema,
    "wiki_write": wiki_write.schema,
}


def register(mcp: MCPServer) -> None:
    """Register wiki authoring tools."""
    _register_wiki_write(mcp)
    _register_wiki_read(mcp)
    _register_wiki_list(mcp)
    _register_wiki_link(mcp)
    _register_wiki_adr(mcp)
    _register_wiki_reindex(mcp)
    _register_wiki_purge(mcp)
    _register_wiki_verify(mcp)
    _register_wiki_rename(mcp)
    _register_wiki_migrate(mcp)


def _register_wiki_write(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_write", **tool_kwargs(wiki_write.schema))
    async def tool_wiki_write(
        path: str,
        content: str,
        mode: str = "create",
        tags: list[str] | None = None,
        memory_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Author a wiki page (create/append/replace) with the provided markdown."""
        return await safe_handler(
            wiki_write.handler,
            {
                "path": path,
                "content": content,
                "mode": mode,
                "tags": tags or [],
                "memory_ids": memory_ids or [],
            },
            tool_name="wiki_write",
        )


def _register_wiki_read(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_read", **tool_kwargs(wiki_read.schema))
    async def tool_wiki_read(
        path: str, follow_redirects: bool = True
    ) -> dict[str, Any]:
        """Read the raw markdown of a wiki page by relative path.

        Phase 3.2 of ADR-2244: redirect stubs are followed transparently
        by default. Pass ``follow_redirects=False`` to read the stub itself.
        """
        return await safe_handler(
            wiki_read.handler,
            {"path": path, "follow_redirects": follow_redirects},
            tool_name="wiki_read",
        )


def _register_wiki_list(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_list", **tool_kwargs(wiki_list.schema))
    async def tool_wiki_list(
        kind: str | None = None,
        include_redirects: bool = False,
        include_auto_generated: bool = False,
    ) -> dict[str, Any]:
        """List authored wiki pages, optionally filtered by kind.

        Phase 3.2: redirect stubs excluded by default.
        Phase 5: auto-generated pages (``provenance: auto-generated``)
        excluded by default — they'd otherwise dominate listings at
        ~8,700 pages. Opt in with ``include_auto_generated=True``.
        """
        return await safe_handler(
            wiki_list.handler,
            {
                "kind": kind,
                "include_redirects": include_redirects,
                "include_auto_generated": include_auto_generated,
            },
            tool_name="wiki_list",
        )


def _register_wiki_link(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_link", **tool_kwargs(wiki_link.schema))
    async def tool_wiki_link(
        from_path: str, to_path: str, relation: str
    ) -> dict[str, Any]:
        """Add a bidirectional link between two wiki pages (Related section)."""
        return await safe_handler(
            wiki_link.handler,
            {"from_path": from_path, "to_path": to_path, "relation": relation},
            tool_name="wiki_link",
        )


def _register_wiki_adr(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_adr", **tool_kwargs(wiki_adr.schema))
    async def tool_wiki_adr(
        title: str,
        context: str,
        decision: str,
        consequences: str,
        status: str = "accepted",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a numbered ADR with auto-incremented sequence."""
        return await safe_handler(
            wiki_adr.handler,
            {
                "title": title,
                "context": context,
                "decision": decision,
                "consequences": consequences,
                "status": status,
                "tags": tags or [],
            },
            tool_name="wiki_adr",
        )


def _register_wiki_reindex(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_reindex", **tool_kwargs(wiki_reindex.schema))
    async def tool_wiki_reindex() -> dict[str, Any]:
        """Regenerate the wiki table of contents at .generated/INDEX.md."""
        return await safe_handler(wiki_reindex.handler, {}, tool_name="wiki_reindex")


def _register_wiki_purge(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_purge", **tool_kwargs(wiki_purge.schema))
    async def tool_wiki_purge(
        apply: bool = False,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """Re-evaluate and purge wiki pages that fail the current classifier."""
        return await safe_handler(
            wiki_purge.handler,
            {"apply": apply, "kind": kind},
            tool_name="wiki_purge",
        )


def _register_wiki_verify(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_verify", **tool_kwargs(wiki_verify.schema))
    async def tool_wiki_verify(path: str | None = None) -> dict[str, Any]:
        """Verify wiki-page symbol citations against AP's code graph
        (ADR-0046 Phase 2)."""
        return await safe_handler(
            wiki_verify.handler,
            {"path": path} if path else {},
            tool_name="wiki_verify",
        )


def _register_wiki_migrate(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_migrate", **tool_kwargs(wiki_migrate.schema))
    async def tool_wiki_migrate(dry_run: bool = True) -> dict[str, Any]:
        """Sync the filesystem wiki into PG and reconcile FS-deleted ghosts.

        Defaults to dry_run=true (report ghost rel_paths without
        deleting). Pass dry_run=false to actually purge.
        """
        return await safe_handler(
            wiki_migrate.handler,
            {"dry_run": dry_run},
            tool_name="wiki_migrate",
        )


def _register_wiki_rename(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_rename", **tool_kwargs(wiki_rename.schema))
    async def tool_wiki_rename(
        from_path: str,
        to_path: str,
        reason: str = "",
        overwrite_dest: bool = False,
    ) -> dict[str, Any]:
        """Move a page and leave a redirect stub at the old path.

        Phase 3.2 of ADR-2244 — the building block for Phase 4 bulk renames.
        Requires the source page to have a stable frontmatter ``id`` (run
        ``scripts/wiki_backfill_ids.py --apply`` first).
        """
        return await safe_handler(
            wiki_rename.handler,
            {
                "from_path": from_path,
                "to_path": to_path,
                "reason": reason,
                "overwrite_dest": overwrite_dest,
            },
            tool_name="wiki_rename",
        )
