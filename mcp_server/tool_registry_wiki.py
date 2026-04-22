"""Tool registration: wiki authoring tools (7 tools).

Registers the authoring surface that lets Claude maintain a first-class
Markdown wiki (ADRs, specs, file docs, notes) alongside PostgreSQL
memory. Pages are never derived from PG — they are authored via these
tools and indexed in PG as protected pointer memories for recall.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import (
    wiki_adr,
    wiki_link,
    wiki_list,
    wiki_purge,
    wiki_read,
    wiki_reindex,
    wiki_verify,
    wiki_write,
)
from mcp_server.tool_error_handler import safe_handler


def register(mcp: FastMCP) -> None:
    """Register wiki authoring tools."""
    _register_wiki_write(mcp)
    _register_wiki_read(mcp)
    _register_wiki_list(mcp)
    _register_wiki_link(mcp)
    _register_wiki_adr(mcp)
    _register_wiki_reindex(mcp)
    _register_wiki_purge(mcp)
    _register_wiki_verify(mcp)


def _register_wiki_write(mcp: FastMCP) -> None:
    @mcp.tool(name="wiki_write", description=wiki_write.schema["description"])
    async def tool_wiki_write(
        path: str,
        content: str,
        mode: str = "create",
        tags: list[str] | None = None,
    ) -> str:
        """Author a wiki page (create/append/replace) with the provided markdown."""
        return await safe_handler(
            wiki_write.handler,
            {
                "path": path,
                "content": content,
                "mode": mode,
                "tags": tags or [],
            },
            tool_name="wiki_write",
        )


def _register_wiki_read(mcp: FastMCP) -> None:
    @mcp.tool(name="wiki_read", description=wiki_read.schema["description"])
    async def tool_wiki_read(path: str) -> str:
        """Read the raw markdown of a wiki page by relative path."""
        return await safe_handler(
            wiki_read.handler, {"path": path}, tool_name="wiki_read"
        )


def _register_wiki_list(mcp: FastMCP) -> None:
    @mcp.tool(name="wiki_list", description=wiki_list.schema["description"])
    async def tool_wiki_list(kind: str | None = None) -> str:
        """List authored wiki pages, optionally filtered by kind."""
        return await safe_handler(
            wiki_list.handler, {"kind": kind}, tool_name="wiki_list"
        )


def _register_wiki_link(mcp: FastMCP) -> None:
    @mcp.tool(name="wiki_link", description=wiki_link.schema["description"])
    async def tool_wiki_link(from_path: str, to_path: str, relation: str) -> str:
        """Add a bidirectional link between two wiki pages (Related section)."""
        return await safe_handler(
            wiki_link.handler,
            {"from_path": from_path, "to_path": to_path, "relation": relation},
            tool_name="wiki_link",
        )


def _register_wiki_adr(mcp: FastMCP) -> None:
    @mcp.tool(name="wiki_adr", description=wiki_adr.schema["description"])
    async def tool_wiki_adr(
        title: str,
        context: str,
        decision: str,
        consequences: str,
        status: str = "accepted",
        tags: list[str] | None = None,
    ) -> str:
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


def _register_wiki_reindex(mcp: FastMCP) -> None:
    @mcp.tool(name="wiki_reindex", description=wiki_reindex.schema["description"])
    async def tool_wiki_reindex() -> str:
        """Regenerate the wiki table of contents at .generated/INDEX.md."""
        return await safe_handler(wiki_reindex.handler, {}, tool_name="wiki_reindex")


def _register_wiki_purge(mcp: FastMCP) -> None:
    @mcp.tool(name="wiki_purge", description=wiki_purge.schema["description"])
    async def tool_wiki_purge(
        apply: bool = False,
        kind: str | None = None,
    ) -> str:
        """Re-evaluate and purge wiki pages that fail the current classifier."""
        return await safe_handler(
            wiki_purge.handler,
            {"apply": apply, "kind": kind},
            tool_name="wiki_purge",
        )


def _register_wiki_verify(mcp: FastMCP) -> None:
    @mcp.tool(name="wiki_verify", description=wiki_verify.schema["description"])
    async def tool_wiki_verify(path: str | None = None) -> str:
        """Verify wiki-page symbol citations against AP's code graph (ADR-0046 Phase 2)."""
        return await safe_handler(
            wiki_verify.handler,
            {"path": path} if path else {},
            tool_name="wiki_verify",
        )
