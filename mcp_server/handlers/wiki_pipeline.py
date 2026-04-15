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
        "Drive the wiki redesign pipeline end-to-end in one call: "
        "extract → resolve → emerge → synthesize → curate → compile. Each "
        "stage is delegated to its own handler (`wiki_extract`, "
        "`wiki_resolve`, `wiki_emerge`, `wiki_synthesize`, `wiki_curate`, "
        "`wiki_compile`) and its summary is preserved in the response. Use "
        "this on fresh installs, after backfilling memories, or as a "
        "scheduled job; for surgical control over a single phase, call the "
        "individual handlers instead. Per-stage errors are captured (never "
        "raised), so a failure in one phase does not abort the rest. Mutates "
        "wiki.* tables and (unless skip_compile) the wiki/ filesystem tree. "
        "Latency varies (~10s-5min depending on memory corpus). Returns "
        "{stages: per-handler summary, pages_published, drafts_approved, "
        "concepts_inserted, claims_inserted}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "limit_per_stage": {
                "type": "integer",
                "description": (
                    "Cap on the number of items each stage processes. Acts as "
                    "a back-pressure knob — start low for safety, raise once "
                    "the pipeline is known-good."
                ),
                "default": 500,
                "minimum": 1,
                "maximum": 50000,
                "examples": [200, 500, 5000],
            },
            "skip_compile": {
                "type": "boolean",
                "description": (
                    "Stop after the curate stage — approved drafts stay in "
                    "wiki.drafts unpublished. Useful when you want to review "
                    "verdicts before any .md files are written."
                ),
                "default": False,
                "examples": [False, True],
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
