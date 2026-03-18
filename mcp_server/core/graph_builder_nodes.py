"""Node construction helpers for the unified graph builder.

Each function appends nodes (and direct parent-child edges) for one node type.
Pure business logic -- no I/O.

Memory and entity node builders live in graph_builder_memory.py.
"""

from __future__ import annotations

from typing import Any

DOMAIN_COLOR = "#6366f1"
ENTRY_COLOR = "#00d4ff"
PATTERN_COLOR = "#10b981"
TOOL_COLOR = "#f59e0b"
FEATURE_COLOR = "#a855f7"
MEMORY_COLORS = {"episodic": "#26de81", "semantic": "#d946ef"}
ENTITY_COLORS = {
    "function": "#00d2ff",
    "dependency": "#3b82f6",
    "error": "#ff4444",
    "decision": "#ffaa00",
    "technology": "#8b5cf6",
    "file": "#6366f1",
    "variable": "#06b6d4",
}
EDGE_COLORS = {
    "has-entry": "#00d4ff",
    "has-pattern": "#10b981",
    "uses-tool": "#f59e0b",
    "has-feature": "#a855f7",
    "memory-entity": "#556677",
    "domain-entity": "#4488aa",
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
        nid = next_id("entry")
        freq = ep.get("frequency") or 0
        nodes.append(
            {
                "id": nid,
                "type": "entry-point",
                "label": ep.get("pattern", ""),
                "domain": domain_key,
                "color": ENTRY_COLOR,
                "size": max(3, min(12, (freq or 1) * 1.5)),
                "group": domain_key,
                "confidence": ep.get("confidence") or 0,
                "frequency": freq,
                "content": ep.get("pattern", ""),
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
