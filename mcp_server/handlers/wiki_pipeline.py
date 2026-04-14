"""Wiki pipeline runner — stitches Phase 2-2.5 handlers into one call.

    extract → resolve → emerge → synthesize → curate → compile

Used at setup / backfill time so fresh installs go from raw memories
to published pages without manual tool chaining. Each stage's summary
is retained so the caller can see what happened.

Never raises: per-stage errors are captured in the summary. A later
stage that has nothing to process simply returns zero counts and the
pipeline moves on.
"""

from __future__ import annotations

from typing import Any


schema = {
    "description": (
        "Run the full wiki pipeline end-to-end: extract claims from "
        "memories, resolve entities/supersedes/conflicts, emerge concepts, "
        "synthesize drafts, curate, compile published pages. Returns a "
        "per-stage summary."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "limit_per_stage": {
                "type": "integer",
                "default": 500,
                "description": "Max items processed per stage.",
            },
            "skip_compile": {
                "type": "boolean",
                "default": False,
                "description": "Stop after curate — leave approved drafts unpublished.",
            },
        },
    },
}


async def _safe_call(label: str, coro) -> tuple[str, dict]:
    """Run a handler coroutine; return its summary or an error dict."""
    try:
        result = await coro
    except Exception as e:
        return label, {"error": str(e)}
    return label, result or {}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    limit = int(args.get("limit_per_stage", 500))
    skip_compile = bool(args.get("skip_compile", False))

    from mcp_server.handlers.wiki_compile import handler as h_compile
    from mcp_server.handlers.wiki_curate import handler as h_curate
    from mcp_server.handlers.wiki_emerge import handler as h_emerge
    from mcp_server.handlers.wiki_extract import handler as h_extract
    from mcp_server.handlers.wiki_resolve import handler as h_resolve
    from mcp_server.handlers.wiki_synthesize import handler as h_synth

    stages: list[tuple[str, dict]] = []

    stages.append(await _safe_call("extract", h_extract({"limit": limit})))
    stages.append(await _safe_call("resolve", h_resolve({"limit": limit})))
    stages.append(await _safe_call("emerge", h_emerge({"limit": limit})))
    stages.append(await _safe_call("synthesize", h_synth({"limit": limit})))
    stages.append(await _safe_call("curate", h_curate({"limit": limit})))
    if not skip_compile:
        stages.append(await _safe_call("compile", h_compile({"limit": limit})))

    summary = {label: result for label, result in stages}

    return {
        "stages": summary,
        "pages_published": summary.get("compile", {}).get("drafts_published", 0),
        "drafts_approved": summary.get("curate", {}).get("approved", 0),
        "concepts_inserted": summary.get("emerge", {}).get("concepts_inserted", 0),
        "claims_inserted": summary.get("extract", {}).get("claims_inserted", 0),
    }
