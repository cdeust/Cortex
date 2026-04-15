"""Handler for the list_domains tool — domain overview."""

from __future__ import annotations

from mcp_server.infrastructure.profile_store import load_profiles

schema = {
    "description": (
        "Return an overview of every cognitive domain Cortex has profiled, "
        "sorted by session count. For each domain: id, human label, session "
        "count, confidence, last active timestamp, top-3 work categories with "
        "ratios, and dominant session-shape mode. Use this to discover what "
        "domains exist before scoping recall, narrate, or rebuild_profiles. "
        "Sub-10ms latency. Takes no arguments."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {},
        "additionalProperties": False,
    },
}


async def handler(args: dict | None = None) -> dict:
    profiles = load_profiles()
    domains = []

    for d in (profiles.get("domains") or {}).values():
        top_categories = sorted(
            (d.get("categories") or {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]

        domains.append(
            {
                "id": d.get("id"),
                "label": d.get("label"),
                "sessionCount": d.get("sessionCount", 0),
                "confidence": d.get("confidence", 0),
                "lastActive": d.get("lastUpdated"),
                "topCategories": [
                    {"category": cat, "ratio": ratio} for cat, ratio in top_categories
                ],
                "dominantMode": d.get("sessionShape", {}).get("dominantMode")
                if d.get("sessionShape")
                else None,
            }
        )

    domains.sort(key=lambda x: x["sessionCount"], reverse=True)

    return {
        "domains": domains,
        "totalDomains": len(domains),
        "globalStyle": profiles.get("globalStyle"),
    }
