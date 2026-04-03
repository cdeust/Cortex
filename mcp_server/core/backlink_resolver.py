"""Backlink resolution — group and rank memories linked to an entity.

Takes raw backlink data from infrastructure layer and organizes it
for display: grouped by domain, sorted by relevance (heat + confidence).

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any


def resolve_backlinks(
    raw_backlinks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Group and rank backlinks for display.

    Args:
        raw_backlinks: List of memory dicts with link_confidence field.

    Returns:
        {
            total: int,
            by_domain: {domain: [memories]},
            top: [top 10 by relevance]
        }
    """
    if not raw_backlinks:
        return {"total": 0, "by_domain": {}, "top": []}

    scored = [
        {**bl, "relevance": _compute_relevance(bl)}
        for bl in raw_backlinks
    ]
    scored.sort(key=lambda x: x["relevance"], reverse=True)

    by_domain: dict[str, list[dict[str, Any]]] = {}
    for bl in scored:
        domain = bl.get("domain", "unknown")
        by_domain.setdefault(domain, []).append(_format_backlink(bl))

    return {
        "total": len(scored),
        "by_domain": by_domain,
        "top": [_format_backlink(bl) for bl in scored[:10]],
    }


def _compute_relevance(backlink: dict[str, Any]) -> float:
    """Score a backlink by heat, confidence, and protection status.

    Higher heat = more active memory.
    Higher confidence = stronger entity link.
    Protected memories get a bonus.
    """
    heat = backlink.get("heat", 0.0)
    confidence = backlink.get("link_confidence", 0.5)
    protected_bonus = 0.2 if backlink.get("is_protected") else 0.0
    return heat * 0.5 + confidence * 0.3 + protected_bonus


def _format_backlink(bl: dict[str, Any]) -> dict[str, Any]:
    """Format a backlink for frontend display."""
    content = bl.get("content", "")
    return {
        "memory_id": bl["id"],
        "snippet": content[:120] + ("..." if len(content) > 120 else ""),
        "domain": bl.get("domain", ""),
        "heat": round(bl.get("heat", 0.0), 3),
        "relevance": round(bl.get("relevance", 0.0), 3),
        "store_type": bl.get("store_type", "episodic"),
        "created_at": str(bl.get("created_at", "")),
        "is_protected": bl.get("is_protected", False),
        "is_global": bl.get("is_global", False),
        "tags": bl.get("tags", []),
    }
