"""Handler for the detect_domain tool — lightweight domain classification."""

from __future__ import annotations

from mcp_server.core.domain_detector import detect_domain
from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.handlers._tool_meta import READ_ONLY

schema = {
    "title": "Detect domain",
    "annotations": READ_ONLY,
    "description": (
        "Classify the current working directory + first message into one "
        "of the known cognitive domains via a 3-signal weighted score: "
        "(1) path tokens (last 3 segments + git root), (2) project ID "
        "match against known profiles, (3) keyword overlap with stored "
        "domain vocabularies. Returns the best-matching domain plus "
        "confidence and the runner-up alternatives. Use this when "
        "switching codebases or contexts to recalibrate, or as a cheap "
        "preflight before `query_methodology` / `recall`. Distinct from "
        "`query_methodology` (returns the FULL profile body, not just "
        "the domain id), `list_domains` (enumerates ALL domains), and "
        "`rebuild_profiles` (rescans, doesn't classify). Read-only. "
        "Latency <20ms. Returns {domain, confidence, "
        "alternativeDomains, signals}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "cwd": {
                "type": "string",
                "description": (
                    "Absolute path to the current working directory. Used to "
                    "match against known project paths and extract path-token "
                    "signals (last 3 segments)."
                ),
                "examples": ["/Users/alice/code/cortex", "/home/dev/projects/api"],
            },
            "project": {
                "type": "string",
                "description": (
                    "Claude Code project identifier (the slugified path used "
                    "under ~/.claude/projects/). Falls back to deriving from cwd."
                ),
                "examples": ["-Users-alice-code-cortex"],
            },
            "first_message": {
                "type": "string",
                "description": (
                    "The first user message of the session, used for keyword-"
                    "based domain inference when path signals are weak."
                ),
                "examples": ["fix the recall pipeline regression"],
            },
        },
    },
}


async def handler(args: dict | None = None) -> dict:
    args = args or {}
    profiles = load_profiles()
    return detect_domain(
        {
            "cwd": args.get("cwd"),
            "project": args.get("project"),
            "first_message": args.get("first_message"),
        },
        profiles,
    )
