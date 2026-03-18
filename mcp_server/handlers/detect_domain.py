"""Handler for the detect_domain tool — lightweight domain classification."""

from __future__ import annotations

from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.core.domain_detector import detect_domain

schema = {
    "description": "Lightweight domain classification from cwd, project, or first message. <20ms.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "description": "Current working directory"},
            "project": {"type": "string", "description": "Project identifier"},
            "first_message": {"type": "string", "description": "First user message"},
        },
        "required": [],
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
