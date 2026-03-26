"""Node quality scoring for the unified graph.

Every node gets a `quality` score (0.0–1.0) and a `qualityLabel` explaining
*why* it has that score. This replaces standalone benchmark nodes — the
evaluation layer is attached directly to the data it describes.

Quality signals per node type:
  - domain:      session volume, confidence, pattern diversity, connection count
  - entry-point: frequency, confidence
  - recurring-pattern: frequency, confidence, uniqueness (low freq = noise)
  - tool-preference: usage ratio (high = essential, low = noise)
  - behavioral-feature: activation magnitude (high = significant)
  - memory:      heat, importance, access count, recall rank (when available)
  - entity:      heat, connection count

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any


def score_all_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """Annotate every node in-place with `quality` (0–1) and `qualityLabel`."""
    conn_counts = _count_connections(nodes, edges)
    total_nodes = len(nodes)

    for node in nodes:
        nid = node["id"]
        conns = conn_counts.get(nid, 0)
        q, label = _score_node(node, conns, total_nodes)
        node["quality"] = round(q, 3)
        node["qualityLabel"] = label


def _count_connections(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, int]:
    """Count edges per node id."""
    counts: dict[str, int] = {}
    for e in edges:
        s = e.get("source", "")
        t = e.get("target", "")
        counts[s] = counts.get(s, 0) + 1
        counts[t] = counts.get(t, 0) + 1
    return counts


def _score_node(node: dict[str, Any], conns: int, total: int) -> tuple[float, str]:
    """Compute quality score and label for a single node."""
    ntype = node.get("type", "")
    scorers = {
        "domain": _score_domain,
        "entry-point": _score_entry,
        "recurring-pattern": _score_pattern,
        "tool-preference": _score_tool,
        "behavioral-feature": _score_feature,
        "memory": _score_memory,
        "entity": _score_entity,
    }
    scorer = scorers.get(ntype, _score_default)
    return scorer(node, conns, total)


def _score_domain(n: dict, conns: int, total: int) -> tuple[float, str]:
    sessions = n.get("sessionCount", 0)
    conf = n.get("confidence", 0)
    parts = []
    q = 0.0
    # Session volume: 10+ sessions = strong, 2-9 = moderate
    if sessions >= 20:
        q += 0.4
        parts.append(f"{sessions} sessions (strong)")
    elif sessions >= 5:
        q += 0.25
        parts.append(f"{sessions} sessions (moderate)")
    else:
        q += 0.1
        parts.append(f"{sessions} sessions (sparse)")
    # Confidence
    q += min(conf, 1.0) * 0.3
    parts.append(f"confidence {conf:.0%}")
    # Connection richness (patterns, tools, features attached)
    conn_score = min(conns / 20, 1.0) * 0.3
    q += conn_score
    parts.append(f"{conns} connections")
    return min(q, 1.0), " | ".join(parts)


def _score_entry(n: dict, conns: int, total: int) -> tuple[float, str]:
    freq = n.get("frequency", 0)
    conf = n.get("confidence", 0)
    if freq >= 5:
        q = 0.7 + min(conf, 1.0) * 0.3
        label = f"frequent ({freq}x) entry point"
    elif freq >= 2:
        q = 0.4 + min(conf, 1.0) * 0.2
        label = f"moderate ({freq}x) entry point"
    else:
        q = 0.15
        label = "rare entry point — may be noise"
    return min(q, 1.0), label


def _score_pattern(n: dict, conns: int, total: int) -> tuple[float, str]:
    freq = n.get("frequency", 0)
    conf = n.get("confidence", 0)
    if freq >= 5:
        q = 0.6 + min(conf, 1.0) * 0.3
        label = f"strong pattern ({freq}x)"
    elif freq >= 2:
        q = 0.3 + min(conf, 1.0) * 0.2
        label = f"moderate pattern ({freq}x)"
    else:
        q = 0.1
        label = "weak pattern — likely noise"
    # Bonus for being connected to multiple domains
    if conns > 3:
        q = min(q + 0.1, 1.0)
        label += f", {conns} connections"
    return min(q, 1.0), label


def _score_tool(n: dict, conns: int, total: int) -> tuple[float, str]:
    ratio = n.get("ratio", 0)
    avg = n.get("avgPerSession", 0)
    if ratio >= 0.5:
        q = 0.8
        label = f"core tool ({ratio:.0%} usage)"
    elif ratio >= 0.2:
        q = 0.5
        label = f"regular tool ({ratio:.0%} usage)"
    else:
        q = 0.2
        label = f"rare tool ({ratio:.0%} usage)"
    if avg >= 3:
        q = min(q + 0.15, 1.0)
        label += f", {avg:.1f}/session"
    return q, label


def _score_feature(n: dict, conns: int, total: int) -> tuple[float, str]:
    act = abs(n.get("activation", 0))
    if act >= 0.5:
        q = 0.8
        label = f"strong feature (activation {act:.2f})"
    elif act >= 0.2:
        q = 0.5
        label = f"moderate feature (activation {act:.2f})"
    else:
        q = 0.15
        label = f"weak feature (activation {act:.2f}) — may be noise"
    return q, label


def _score_memory(n: dict, conns: int, total: int) -> tuple[float, str]:
    heat = n.get("heat", 0)
    imp = n.get("importance", 0.5)
    acc = n.get("accessCount", 0)
    rank = n.get("lastRecallRank")  # None if never recalled
    parts = []
    q = 0.0
    # Heat: active memories score higher
    q += min(heat, 1.0) * 0.3
    parts.append(f"heat {heat:.2f}")
    # Importance
    q += min(imp, 1.0) * 0.25
    parts.append(f"importance {imp:.2f}")
    # Access count: frequently accessed = validated
    if acc >= 5:
        q += 0.2
        parts.append(f"accessed {acc}x")
    elif acc >= 1:
        q += 0.1
        parts.append(f"accessed {acc}x")
    else:
        parts.append("never accessed")
    # Recall rank: the key benchmark signal
    if rank is not None:
        if rank <= 3:
            q += 0.25
            parts.append(f"recall rank #{rank} (excellent)")
        elif rank <= 10:
            q += 0.15
            parts.append(f"recall rank #{rank} (top 10)")
        elif rank <= 20:
            q += 0.05
            parts.append(f"recall rank #{rank} (retrievable)")
        else:
            parts.append(f"recall rank #{rank} (hard to find)")
    else:
        parts.append("not yet recall-tested")
    return min(q, 1.0), " | ".join(parts)


def _score_entity(n: dict, conns: int, total: int) -> tuple[float, str]:
    heat = n.get("heat", 0)
    if conns >= 5:
        q = 0.7 + min(heat, 1.0) * 0.2
        label = f"well-connected entity ({conns} edges)"
    elif conns >= 2:
        q = 0.4 + min(heat, 1.0) * 0.2
        label = f"connected entity ({conns} edges)"
    else:
        q = 0.15
        label = "isolated entity — may be noise"
    return min(q, 1.0), label


def _score_default(n: dict, conns: int, total: int) -> tuple[float, str]:
    return 0.5, "unscored node type"
