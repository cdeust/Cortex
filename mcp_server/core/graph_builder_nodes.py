"""Node construction helpers for the unified graph builder.

Each function appends nodes (and direct parent-child edges) for one node type.
Pure business logic -- no I/O.

Memory and entity node builders live in graph_builder_memory.py.
"""

from __future__ import annotations

from typing import Any

DOMAIN_COLOR = "#E8B840"
ENTRY_COLOR = "#60D8F0"
PATTERN_COLOR = "#70D880"
TOOL_COLOR = "#E0A840"
FEATURE_COLOR = "#B088E0"
MEMORY_COLORS = {"episodic": "#58D888", "semantic": "#C070D0"}
ENTITY_COLORS = {
    "function": "#50D0E8",
    "dependency": "#60A0E0",
    "error": "#E07070",
    "decision": "#E0C050",
    "technology": "#9080D0",
    "file": "#7088D0",
    "variable": "#50B8D0",
}
EDGE_COLORS = {
    "has-entry": "#50C8E0",
    "has-pattern": "#60C890",
    "uses-tool": "#D0B060",
    "has-feature": "#A080C0",
    "memory-entity": "#40A0B8",
    "domain-entity": "#50B0C8",
}

Node = dict[str, Any]
Edge = dict[str, Any]
IdAllocator = Any  # callable(str) -> str


def add_domain_hub(
    dp: dict,
    domain_key: str,
    next_id: IdAllocator,
    nodes: list[Node],
) -> str:
    """Create a domain hub node and return its id."""
    hub_id = next_id("dom")
    session_count = dp.get("sessionCount") or 0
    nodes.append(
        {
            "id": hub_id,
            "type": "domain",
            "label": dp.get("label") or domain_key,
            "domain": domain_key,
            "color": DOMAIN_COLOR,
            "size": max(6, min(25, (session_count or 1) ** 0.5 * 2)),
            "group": domain_key,
            "sessionCount": session_count,
            "confidence": dp.get("confidence") or 0,
            "content": (
                f"{dp.get('label') or domain_key} -- "
                f"{session_count} sessions, confidence {(dp.get('confidence') or 0):.0%}"
            ),
        }
    )
    return hub_id


def _is_readable_pattern(pattern: str) -> bool:
    """Filter out nonsensical n-gram patterns (hashes, random word combos)."""
    import re

    if not pattern or len(pattern) < 3:
        return False
    parts = [p.strip() for p in pattern.replace("/", " ").split()]
    # Reject if any token looks like a hex hash (>8 hex chars)
    for p in parts:
        if len(p) > 8 and re.fullmatch(r"[0-9a-f]+", p):
            return False
    # Reject generic stopword-only patterns
    stopwords = {
        "json",
        "general",
        "against",
        "through",
        "already",
        "instead",
        "context",
        "updates",
        "meaning",
        "continue",
        "connect",
        "acceptable",
        "violating",
        "interactive",
        "verified",
        "updated",
        "internal",
        "background",
    }
    meaningful = [p for p in parts if len(p) > 2 and p.lower() not in stopwords]
    return len(meaningful) >= 1


def add_entry_points(
    dp: dict,
    domain_key: str,
    hub_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Add entry-point nodes linked to the domain hub."""
    for ep in dp.get("entryPoints") or []:
        pattern = ep.get("pattern", "")
        if not _is_readable_pattern(pattern):
            continue
        # Clean up " / " separated n-grams into readable labels
        label = pattern.replace(" / ", ", ")
        nid = next_id("entry")
        freq = ep.get("frequency") or 0
        nodes.append(
            {
                "id": nid,
                "type": "entry-point",
                "label": label,
                "domain": domain_key,
                "color": ENTRY_COLOR,
                "size": max(3, min(12, (freq or 1) * 1.5)),
                "group": domain_key,
                "confidence": ep.get("confidence") or 0,
                "frequency": freq,
                "content": pattern,
            }
        )
        edges.append(
            {
                "source": hub_id,
                "target": nid,
                "type": "has-entry",
                "weight": ep.get("confidence") or 0.5,
                "color": EDGE_COLORS["has-entry"],
            }
        )


def add_recurring_patterns(
    dp: dict,
    domain_key: str,
    hub_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Add recurring-pattern nodes linked to the domain hub."""
    for rp in dp.get("recurringPatterns") or []:
        nid = next_id("pat")
        freq = rp.get("frequency") or 0
        nodes.append(
            {
                "id": nid,
                "type": "recurring-pattern",
                "label": rp.get("pattern", ""),
                "domain": domain_key,
                "color": PATTERN_COLOR,
                "size": max(3, min(12, (freq or 1) * 1.2)),
                "group": domain_key,
                "confidence": rp.get("confidence") or 0,
                "frequency": freq,
                "content": rp.get("pattern", ""),
            }
        )
        edges.append(
            {
                "source": hub_id,
                "target": nid,
                "type": "has-pattern",
                "weight": rp.get("confidence") or 0.5,
                "color": EDGE_COLORS["has-pattern"],
            }
        )


def _build_tool_node(tool_name: str, pref: dict, nid: str, domain_key: str) -> Node:
    """Construct a single tool-preference node dict."""
    ratio = pref.get("ratio", 0)
    return {
        "id": nid,
        "type": "tool-preference",
        "label": tool_name,
        "domain": domain_key,
        "color": TOOL_COLOR,
        "size": max(3, min(10, ratio * 10)),
        "group": domain_key,
        "ratio": ratio,
        "avgPerSession": pref.get("avgPerSession", 0),
        "content": f"{tool_name} (usage: {ratio:.0%}, avg/session: {pref.get('avgPerSession', 0)})",
    }


def add_tool_preferences(
    dp: dict,
    domain_key: str,
    hub_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Add top-5 tool-preference nodes linked to the domain hub."""
    tool_prefs = dp.get("toolPreferences") or {}
    top_tools = sorted(
        tool_prefs.items(), key=lambda x: x[1].get("ratio", 0), reverse=True
    )[:5]
    for tool_name, pref in top_tools:
        nid = next_id("tool")
        nodes.append(_build_tool_node(tool_name, pref, nid, domain_key))
        edges.append(
            {
                "source": hub_id,
                "target": nid,
                "type": "uses-tool",
                "weight": pref.get("ratio", 0),
                "color": EDGE_COLORS["uses-tool"],
            }
        )


def add_behavioral_features(
    dp: dict,
    domain_key: str,
    hub_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Add behavioral-feature nodes with activation above threshold."""
    for feat_label, weight in (dp.get("featureActivations") or {}).items():
        if abs(weight) < 0.05:
            continue
        nid = next_id("feat")
        nodes.append(
            {
                "id": nid,
                "type": "behavioral-feature",
                "label": feat_label,
                "domain": domain_key,
                "color": FEATURE_COLOR,
                "size": max(2, min(8, abs(weight) * 10)),
                "group": domain_key,
                "activation": weight,
                "content": f"{feat_label} (activation: {weight:+.3f})",
            }
        )
        edges.append(
            {
                "source": hub_id,
                "target": nid,
                "type": "has-feature",
                "weight": abs(weight),
                "color": EDGE_COLORS["has-feature"],
            }
        )
