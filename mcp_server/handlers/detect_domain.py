"""Handler for the detect_domain tool — lightweight domain classification."""

from __future__ import annotations

from mcp_server.core.domain_detector import detect_domain
from mcp_server.infrastructure.profile_store import load_profiles

schema = {
    "description": (
        "Lightweight domain classification from working directory, project ID, or "
        "the user's first message. Combines three weighted signals (path tokens, "
        "project ID match against known profiles, keyword overlap with stored "
        "domain vocabularies) and returns the best-matching domain plus a "
        "confidence score. Use this when switching codebases or contexts to "
        "recalibrate Cortex's cognitive profile lookup. Sub-20ms latency."
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
