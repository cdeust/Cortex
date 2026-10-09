"""Statistics derived from a domain's conversations and from the domain set."""

from __future__ import annotations

from mcp_server.shared.categorizer import categorize_with_scores


def compute_category_distribution(convs: list[dict]) -> dict[str, float]:
    """Compute multi-category distribution across conversations."""
    categories: dict[str, float] = {}
    total = 0
    for conv in convs:
        text = conv.get("allText") or conv.get("firstMessage") or ""
        if not text:
            continue
        scores = categorize_with_scores(text)
        for cat in scores:
            categories[cat] = categories.get(cat, 0) + 1
        if not scores:
            categories["general"] = categories.get("general", 0) + 1
        total += 1

    if total > 0:
        for cat in categories:
            categories[cat] = round((categories[cat] / total) * 100) / 100

    return categories


def extract_top_keywords(convs: list[dict], limit: int = 20) -> list[str]:
    """Extract the most frequent keywords across conversations."""
    freq: dict[str, int] = {}
    for conv in convs:
        kws = conv.get("keywords")
        if not kws:
            continue
        for kw in kws if isinstance(kws, (list, set)) else []:
            freq[kw] = freq.get(kw, 0) + 1
    return [
        kw for kw, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:limit]
    ]


def compute_timestamps(convs: list[dict]) -> tuple[str | None, str | None]:
    """Extract first_seen and last_updated from sorted timestamps."""
    timestamps = sorted(
        t for c in convs for t in [c.get("startedAt") or c.get("endedAt")] if t
    )
    first_seen = timestamps[0] if timestamps else None
    last_updated = timestamps[-1] if timestamps else None
    return first_seen, last_updated


def compute_global_style(profiles: dict) -> None:
    """Compute session-weighted global cognitive style across all domains."""
    all_domains = list(profiles.get("domains", {}).values())
    if not all_domains:
        return

    total_sessions = 0
    ar_sum = si_sum = sg_sum = 0.0
    for d in all_domains:
        sc = d.get("sessionCount") or 0
        total_sessions += sc
        mc = d.get("metacognitive") or {}
        ar_sum += (mc.get("activeReflective") or 0) * sc
        si_sum += (mc.get("sensingIntuitive") or 0) * sc
        sg_sum += (mc.get("sequentialGlobal") or 0) * sc

    if total_sessions > 0:
        profiles["globalStyle"] = {
            "activeReflective": round((ar_sum / total_sessions) * 100) / 100,
            "sensingIntuitive": round((si_sum / total_sessions) * 100) / 100,
            "sequentialGlobal": round((sg_sum / total_sessions) * 100) / 100,
            "confidence": round(min(total_sessions / 100, 1.0) * 100) / 100,
            "sessionCount": total_sessions,
        }
