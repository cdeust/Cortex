"""Handler: wiki_verify — check whether a wiki page's cited symbols still
exist in the AP code graph (ADR-0046 Phase 2).

Composition root: filesystem wiki → symbol extractor (core) → AP bridge
verification (infrastructure) → verdict (core). Returns a structured
report per page.

When AP is disabled (``CORTEX_ENABLE_AP`` unset), the handler returns
``status: skipped`` with an explanation — never a staleness claim.
Graceful degradation is the invariant.

A single page or the entire wiki can be verified in one call. The
handler only READS the wiki; any flag persistence is the caller's
responsibility (there is no DB column for symbol_stale today).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_symbol_extract import harvest_page_symbols
from mcp_server.core.wiki_symbol_verify import (
    MIN_SYMBOL_REFS,
    STALE_THRESHOLD,
    evaluate_symbol_staleness,
)
from mcp_server.infrastructure.ap_bridge import is_enabled
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import list_pages, read_page
from mcp_server.infrastructure.workflow_graph_source_ast import (
    WorkflowGraphASTSource,
)


schema = {
    "description": (
        "Verify that code symbols cited by wiki pages still resolve in "
        "the AST (via the automatised-pipeline MCP server, ADR-0046 "
        "Phase 2). Takes an optional path (verify one page) or no args "
        "(verify every authored page) and returns per-page verdicts: "
        "{page, symbol_refs, missing_refs, is_symbol_stale, rationale}. "
        "Requires the CORTEX_ENABLE_AP flag; when disabled the handler "
        "returns status=skipped and never produces a stale verdict. "
        "Read-only — never mutates wiki or memory state."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Optional wiki-relative path of a single page to "
                    "verify. Omit to verify the entire wiki."
                ),
            },
        },
    },
}


def _parse_lead_and_sections(md: str) -> dict[str, Any]:
    """Extract ``lead`` (before first ``## `` heading) and ``sections``
    (heading → body) from a wiki markdown page.

    Minimal parser — the goal is to feed ``harvest_page_symbols``, not
    to render. Heading detection matches the wiki's authored style
    (ATX ``## `` at column 0).
    """
    lines = md.splitlines()
    lead_lines: list[str] = []
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            else:
                lead_lines = list(buf)
            current = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    else:
        lead_lines = list(buf)
    return {"lead": "\n".join(lead_lines).strip(), "sections": sections}


def _verify_one(path: str, ast_source: WorkflowGraphASTSource) -> dict[str, Any]:
    """Verify one page by wiki-relative path."""
    content = read_page(WIKI_ROOT, path)
    if content is None:
        return {"page": path, "error": "page not found"}
    page_struct = _parse_lead_and_sections(content)
    symbol_refs = harvest_page_symbols(page_struct)
    # Cap at 200 to keep per-call cost bounded — AP is one RPC per name.
    symbol_refs = symbol_refs[:200]
    existence = ast_source.verify_symbols(symbol_refs) if symbol_refs else {}
    verdict = evaluate_symbol_staleness(
        page_id=path,
        is_symbol_stale_was=False,
        symbol_refs=symbol_refs,
        existence=existence,
    )
    return {
        "page": path,
        "symbol_refs": verdict.symbol_refs,
        "missing_refs": verdict.missing_refs,
        "is_symbol_stale": verdict.is_symbol_stale_now,
        "rationale": verdict.rationale,
    }


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    if not is_enabled():
        return {
            "status": "skipped",
            "reason": "ap_disabled",
            "detail": (
                "Set CORTEX_ENABLE_AP=1 and install automatised-pipeline "
                "to run symbol verification."
            ),
        }
    ast_source = WorkflowGraphASTSource()
    target = str(args.get("path") or "").strip()
    if target:
        result = _verify_one(target, ast_source)
        return {
            "status": "ok",
            "results": [result],
            "threshold": STALE_THRESHOLD,
            "min_refs": MIN_SYMBOL_REFS,
        }
    pages = list_pages(WIKI_ROOT)
    results = [_verify_one(p, ast_source) for p in pages]
    stale = [r for r in results if r.get("is_symbol_stale")]
    return {
        "status": "ok",
        "results": results,
        "summary": {
            "total": len(results),
            "stale": len(stale),
            "threshold": STALE_THRESHOLD,
            "min_refs": MIN_SYMBOL_REFS,
        },
    }


__all__ = ["handler", "schema"]
