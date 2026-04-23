"""Handler for the list_domains tool — domain overview."""

from __future__ import annotations

from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.handlers._tool_meta import READ_ONLY

schema = {
    "title": "List domains",
    "annotations": READ_ONLY,
    "description": (
        "Read profiles.json and emit an overview row for every cognitive "
        "domain Cortex has profiled, sorted by session count. Per domain: "
        "id, human label, sessionCount, confidence, lastActive, top-3 "
        "work categories with ratios, and dominantMode from the session "
        "shape. Use this to discover what domains exist before scoping "
        "`recall`, `narrate`, or `rebuild_profiles`. Distinct from "
        "`query_methodology` (deep profile for ONE domain), "
        "`detect_domain` (classifies the current context, no enumeration), "
        "and `memory_stats` (memory-system counts, not domain profiles). "
        "Read-only. Takes no arguments. Latency <10ms. Returns "
        "{domains: [{id, label, sessionCount, confidence, lastActive, "
        "topCategories, dominantMode}], totalDomains, globalStyle}."
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
