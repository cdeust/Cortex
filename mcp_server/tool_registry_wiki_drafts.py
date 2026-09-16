"""Tool registration: wiki draft refinement, Path B (2 tools).

Path A (`wiki_synthesize`) fills `wiki.drafts` from routed claims at scale.
Path B is the per-draft refinement that turns such a skeleton into prose:
the caller reads a draft with `wiki_get_draft`, writes the sections itself,
and submits them with `wiki_refine_draft`. The pair lives in its own
registry module so `tool_registry_wiki.py` stays inside the 300-line cap.

source: ADR-1066"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_server.handlers import wiki_refine
from mcp_server.handlers._tool_meta import tool_kwargs
from mcp_server.tool_error_handler import safe_handler


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "wiki_get_draft": wiki_refine.schema_get,
    "wiki_refine_draft": wiki_refine.schema_refine,
}


def register(mcp: MCPServer) -> None:
    """Register the Path B draft tools."""
    _register_wiki_get_draft(mcp)
    _register_wiki_refine_draft(mcp)


def _register_wiki_get_draft(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_get_draft", **tool_kwargs(wiki_refine.schema_get))
    async def tool_wiki_get_draft(
        draft_id: int | None = None,
        list_pending: bool = False,
        kind: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Fetch a pending draft with its source claims and kind contract.

        Pass ``list_pending=true`` to list the pending drafts instead, and
        ``kind`` to filter that listing (ADR-1066)."""
        return await safe_handler(
            wiki_refine.handler_get,
            {
                "draft_id": draft_id,
                "list_pending": list_pending,
                "kind": kind,
                "limit": limit,
            },
            tool_name="wiki_get_draft",
        )


def _register_wiki_refine_draft(mcp: MCPServer) -> None:
    @mcp.tool(name="wiki_refine_draft", **tool_kwargs(wiki_refine.schema_refine))
    async def tool_wiki_refine_draft(
        draft_id: int,
        title: str | None = None,
        lead: str | None = None,
        sections: list[dict[str, Any]] | None = None,
        frontmatter: dict[str, Any] | None = None,
        synth_model: str = "claude_refine_v1",
        synth_prompt: str | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Submit refined prose for a draft and record an audit memo.

        Sections are validated against the kind contract ``wiki_get_draft``
        returned; the draft's confidence stays as its claims set it
        (ADR-1065). Registered by ADR-1066."""
        return await safe_handler(
            wiki_refine.handler_refine,
            {
                "draft_id": draft_id,
                "title": title,
                "lead": lead,
                "sections": sections,
                "frontmatter": frontmatter,
                "synth_model": synth_model,
                "synth_prompt": synth_prompt,
                "rationale": rationale,
            },
            tool_name="wiki_refine_draft",
        )
