"""Graph data structures for 3D visualization.

Transforms domain profiles into nodes and edges for a force-directed graph.
"""

from __future__ import annotations

from typing import Any

FEATURE_COLOR = "#a855f7"
PERSISTENT_COLOR = "#ec4899"


class _GraphAccumulator:
    """Mutable state container for incremental graph construction."""

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.blind_spot_regions: list[dict[str, Any]] = []
        self.node_id: int = 0

    def next_id(self, prefix: str) -> str:
        nid = f"{prefix}_{self.node_id}"
        self.node_id += 1
        return nid


def _add_domain_hub(
    acc: _GraphAccumulator,
    domain_id: str,
    dp: dict,
) -> str:
    """Add a domain hub node and return its ID."""
    hub_id = acc.next_id("domain")
    session_count = dp.get("sessionCount") or 0
    acc.nodes.append(
        {
            "id": hub_id,
            "type": "domain",
            "label": dp.get("label") or domain_id,
            "domain": domain_id,
            "confidence": dp.get("confidence") or 0,
            "sessionCount": session_count,
            "color": "#6366f1",
            "size": max(8, min(30, (session_count or 1) * 0.5)),
        }
    )
    return hub_id


def _add_entry_points(
    acc: _GraphAccumulator,
    hub_id: str,
    domain_id: str,
    dp: dict,
) -> None:
    """Add entry point nodes linked to a domain hub."""
    for ep in dp.get("entryPoints") or []:
        ep_id = acc.next_id("entry")
        freq = ep.get("frequency") or 0
        acc.nodes.append(
            {
                "id": ep_id,
                "type": "entry-point",
                "label": ep.get("pattern", ""),
                "domain": domain_id,
                "confidence": ep.get("confidence") or 0,
                "frequency": freq,
                "color": "#00d4ff",
                "size": max(4, min(15, (freq or 1) * 2)),
            }
        )
        acc.edges.append(
            {
                "source": hub_id,
                "target": ep_id,
                "type": "has-entry",
                "weight": ep.get("confidence") or 0.5,
            }
        )


def _add_recurring_patterns(
    acc: _GraphAccumulator,
    hub_id: str,
    domain_id: str,
    dp: dict,
) -> None:
    """Add recurring pattern nodes linked to a domain hub."""
    for rp in dp.get("recurringPatterns") or []:
        rp_id = acc.next_id("pattern")
        freq = rp.get("frequency") or 0
        acc.nodes.append(
            {
                "id": rp_id,
                "type": "recurring-pattern",
                "label": rp.get("pattern", ""),
                "domain": domain_id,
                "confidence": rp.get("confidence") or 0,
                "frequency": freq,
                "color": "#10b981",
                "size": max(4, min(15, (freq or 1) * 1.5)),
            }
        )
        acc.edges.append(
            {
                "source": hub_id,
                "target": rp_id,
                "type": "has-pattern",
                "weight": rp.get("confidence") or 0.5,
            }
        )


def _add_tool_preferences(
    acc: _GraphAccumulator,
    hub_id: str,
    domain_id: str,
    dp: dict,
) -> None:
    """Add top-5 tool preference nodes linked to a domain hub."""
    tool_prefs = dp.get("toolPreferences") or {}
    top_tools = sorted(
        tool_prefs.items(), key=lambda x: x[1].get("ratio", 0), reverse=True
    )[:5]
    for tool, pref in top_tools:
        tool_id = acc.next_id("tool")
        ratio = pref.get("ratio", 0)
        acc.nodes.append(
            {
                "id": tool_id,
                "type": "tool-preference",
                "label": tool,
                "domain": domain_id,
                "ratio": ratio,
                "avgPerSession": pref.get("avgPerSession", 0),
                "color": "#f59e0b",
                "size": max(4, min(12, ratio * 15)),
            }
        )
        acc.edges.append(
            {
                "source": hub_id,
                "target": tool_id,
                "type": "uses-tool",
                "weight": ratio,
            }
        )


def _add_bridges(
    acc: _GraphAccumulator,
    hub_id: str,
    dp: dict,
    domains_to_render: dict,
    domain_keys: list[str],
) -> None:
    """Add bridge edges between domain hubs."""
    for bridge in dp.get("connectionBridges") or []:
        to_domain = bridge.get("toDomain")
        if to_domain not in domains_to_render:
            continue
        target_idx = domain_keys.index(to_domain) if to_domain in domain_keys else -1
        if target_idx >= 0:
            acc.edges.append(
                {
                    "source": hub_id,
                    "target": f"domain_{target_idx}",
                    "type": "bridge",
                    "weight": bridge.get("weight") or 0.5,
                    "label": bridge.get("pattern"),
                }
            )


def _add_blind_spots(
    acc: _GraphAccumulator,
    domain_id: str,
    dp: dict,
) -> None:
    """Collect blind spot regions for a domain."""
    for bs in dp.get("blindSpots") or []:
        acc.blind_spot_regions.append(
            {
                "domain": domain_id,
                "type": bs.get("type"),
                "value": bs.get("value"),
                "severity": bs.get("severity"),
                "description": bs.get("description"),
                "suggestion": bs.get("suggestion"),
            }
        )


def _find_domain_hub(nodes: list[dict[str, Any]], domain_id: str) -> dict | None:
    """Find the hub node for a given domain."""
    return next(
        (n for n in nodes if n["type"] == "domain" and n["domain"] == domain_id),
        None,
    )


def _add_behavioral_features(
    acc: _GraphAccumulator,
    domains_to_render: dict,
) -> None:
    """Add behavioral feature nodes for domains with feature activations."""
    for domain_id, dp in domains_to_render.items():
        if not dp or not dp.get("featureActivations"):
            continue

        hub_node = _find_domain_hub(acc.nodes, domain_id)
        if not hub_node:
            continue

        for label, weight in dp["featureActivations"].items():
            if abs(weight) < 0.05:
                continue
            feature_id = acc.next_id("feature")
            acc.nodes.append(
                {
                    "id": feature_id,
                    "type": "behavioral-feature",
                    "label": label,
                    "domain": domain_id,
                    "activation": weight,
                    "color": FEATURE_COLOR,
                    "size": max(3, min(10, abs(weight) * 12)),
                }
            )
            acc.edges.append(
                {
                    "source": hub_node["id"],
                    "target": feature_id,
                    "type": "has-feature",
                    "weight": abs(weight),
                }
            )


def _add_persistent_feature_edges(
    acc: _GraphAccumulator,
    profiles: dict,
) -> None:
    """Add edges for features that persist across multiple domains."""
    for pf in profiles.get("persistentFeatures") or []:
        pf_domains = pf.get("domains") or []
        if len(pf_domains) < 2:
            continue
        for i in range(len(pf_domains)):
            for j in range(i + 1, len(pf_domains)):
                source_hub = _find_domain_hub(acc.nodes, pf_domains[i])
                target_hub = _find_domain_hub(acc.nodes, pf_domains[j])
                if source_hub and target_hub:
                    acc.edges.append(
                        {
                            "source": source_hub["id"],
                            "target": target_hub["id"],
                            "type": "persistent-feature",
                            "weight": pf.get("persistence", 0),
                            "label": pf.get("label"),
                            "color": PERSISTENT_COLOR,
                        }
                    )


def build_graph(profiles: dict, filter_domain: str | None = None) -> dict[str, Any]:
    """Build a force-directed graph from domain profiles."""
    acc = _GraphAccumulator()

    all_domains = profiles.get("domains") or {}
    if filter_domain:
        domains_to_render = {filter_domain: all_domains.get(filter_domain)}
    else:
        domains_to_render = dict(all_domains)

    domain_keys = list(domains_to_render.keys())

    for domain_id, dp in domains_to_render.items():
        if not dp:
            continue

        hub_id = _add_domain_hub(acc, domain_id, dp)
        _add_entry_points(acc, hub_id, domain_id, dp)
        _add_recurring_patterns(acc, hub_id, domain_id, dp)
        _add_tool_preferences(acc, hub_id, domain_id, dp)
        _add_bridges(acc, hub_id, dp, domains_to_render, domain_keys)
        _add_blind_spots(acc, domain_id, dp)

    _add_behavioral_features(acc, domains_to_render)
    _add_persistent_feature_edges(acc, profiles)

    return {
        "nodes": acc.nodes,
        "edges": acc.edges,
        "blindSpotRegions": acc.blind_spot_regions,
    }
