"""Domain aggregation for the unified graph builder.

Merges domains sharing a common group key (e.g., all "ai architect ..."
sub-paths) into a single aggregate profile, preventing visual clutter.
Pure business logic -- no I/O.
"""

from __future__ import annotations

import re

# Words to strip from path-based domain names before grouping
_PATH_NOISE = frozenset(
    "users documents mac mini de cl ment cle clement developments ios "
    "personal bu business pipeline worktrees builds landing pages "
    "aiprd website 008".split()
)


def domain_group_key(label: str) -> str:
    """Extract a short root name for domain grouping.

    Strips filesystem noise, keeps first 2 meaningful words.
    """
    parts = re.split(r"[\s/\-_]+", label.lower().strip())
    clean = [p for p in parts if p and p not in _PATH_NOISE and len(p) > 1]
    if not clean:
        return label.strip()[:20]
    return " ".join(clean[:2])


def aggregate_domains(all_domains: dict) -> dict[str, dict]:
    """Merge domains sharing the same group key into a single profile.

    Sums sessions, unions entry points / patterns, merges top tools and
    feature activations. Returns {group_key: merged_profile}.
    """
    groups: dict[str, list[tuple[str, dict]]] = {}
    for key, dp in all_domains.items():
        if not dp:
            continue
        gk = domain_group_key(dp.get("label") or key)
        groups.setdefault(gk, []).append((key, dp))

    merged: dict[str, dict] = {}
    for gk, members in groups.items():
        if len(members) == 1:
            orig_key, dp = members[0]
            dp["_orig_keys"] = [orig_key]
            merged[gk] = dp
            continue
        merged[gk] = _merge_profiles(gk, members)

    # Drop trivial domains (< 2 sessions) to reduce noise
    merged = {k: v for k, v in merged.items() if (v.get("sessionCount") or 0) >= 2}
    return merged


def _merge_profiles(
    group_key: str,
    members: list[tuple[str, dict]],
) -> dict:
    """Merge multiple domain profiles into one aggregate profile."""
    total_sessions = sum(dp.get("sessionCount", 0) for _, dp in members)
    max_conf = max((dp.get("confidence", 0) for _, dp in members), default=0)
    orig_keys = [k for k, _ in members]

    entry_points = _union_entries(members)
    patterns = _union_patterns(members)
    tools = _merge_tools(members)
    feat_merged = _merge_features(members)
    bridges = _first_bridges(members)

    pretty_label = group_key.replace("-", " ").title()
    return {
        "label": pretty_label,
        "sessionCount": total_sessions,
        "confidence": max_conf,
        "entryPoints": entry_points[:8],
        "recurringPatterns": patterns,
        "toolPreferences": tools,
        "featureActivations": feat_merged,
        "connectionBridges": bridges,
        "_orig_keys": orig_keys,
    }


def _union_entries(members: list[tuple[str, dict]]) -> list[dict]:
    """Deduplicate entry points by pattern text."""
    seen: set[str] = set()
    result: list[dict] = []
    for _, dp in members:
        for ep in dp.get("entryPoints") or []:
            pat = ep.get("pattern", "")
            if pat not in seen:
                seen.add(pat)
                result.append(ep)
    return result


def _union_patterns(members: list[tuple[str, dict]]) -> list[dict]:
    """Deduplicate recurring patterns, keep top 20 by frequency."""
    seen: set[str] = set()
    result: list[dict] = []
    for _, dp in members:
        for rp in dp.get("recurringPatterns") or []:
            pat = rp.get("pattern", "")
            if pat not in seen:
                seen.add(pat)
                result.append(rp)
    result.sort(key=lambda x: x.get("frequency", 0), reverse=True)
    return result[:20]


def _merge_tools(members: list[tuple[str, dict]]) -> dict[str, dict]:
    """Merge tool preferences (average ratios)."""
    tools: dict[str, dict] = {}
    for _, dp in members:
        for name, pref in (dp.get("toolPreferences") or {}).items():
            if name not in tools:
                tools[name] = {"ratio": 0, "avgPerSession": 0, "_n": 0}
            tools[name]["ratio"] += pref.get("ratio", 0)
            tools[name]["avgPerSession"] += pref.get("avgPerSession", 0)
            tools[name]["_n"] += 1
    for v in tools.values():
        if v["_n"] > 1:
            v["ratio"] /= v["_n"]
            v["avgPerSession"] /= v["_n"]
        del v["_n"]
    return tools


def _merge_features(members: list[tuple[str, dict]]) -> dict[str, float]:
    """Average feature activation weights across members."""
    feats: dict[str, list[float]] = {}
    for _, dp in members:
        for feat, w in (dp.get("featureActivations") or {}).items():
            feats.setdefault(feat, []).append(w)
    return {k: sum(vs) / len(vs) for k, vs in feats.items()}


def _first_bridges(members: list[tuple[str, dict]]) -> list:
    """Take bridge info from first member that has it."""
    for _, dp in members:
        if dp.get("connectionBridges"):
            return dp["connectionBridges"]
    return []
