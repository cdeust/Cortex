"""Discussion node construction for the unified graph builder.

Builds discussion nodes from conversation metadata and links them
to domain hubs via has-discussion edges.

Pure business logic -- no I/O.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.graph_builder_nodes import EDGE_COLORS, Edge, Node

DISCUSSION_COLOR = "#F43F5E"


def _slug_lower(slug: str) -> str:
    """Normalize project slug to lowercase for matching."""
    return slug.lower().replace("-", " ").strip()


def build_discussion_node(conv: dict[str, Any], node_id: str) -> Node:
    """Build a single discussion node from conversation metadata.

    conv keys: sessionId, project, firstMessage, startedAt, endedAt,
               duration, turnCount, messageCount, toolsUsed, keywords,
               fileSize, filePath
    """
    first_msg = conv.get("firstMessage") or ""
    label = first_msg[:50] + ("..." if len(first_msg) > 50 else "")
    project = conv.get("project") or ""
    domain = project
    turn_count = conv.get("turnCount") or 0
    size = max(2, min(8, turn_count**0.4 * 1.5))

    return {
        "id": node_id,
        "type": "discussion",
        "label": label,
        "domain": domain,
        "color": DISCUSSION_COLOR,
        "size": round(size, 2),
        "group": domain,
        "sessionId": conv.get("sessionId"),
        "project": project,
        "firstMessage": first_msg,
        "startedAt": conv.get("startedAt"),
        "endedAt": conv.get("endedAt"),
        "duration": conv.get("duration"),
        "turnCount": turn_count,
        "messageCount": conv.get("messageCount") or 0,
        "toolsUsed": conv.get("toolsUsed") or [],
        "keywords": conv.get("keywords") or [],
        "fileSize": conv.get("fileSize"),
        "content": first_msg[:200],
    }


def build_discussion_nodes(
    conversations: list[dict[str, Any]],
    domain_hub_ids: dict[str, str],
) -> tuple[list[Node], list[Edge]]:
    """Build all discussion nodes and has-discussion edges.

    domain_hub_ids maps domain_key -> node_id of the domain hub.
    Returns (nodes, edges). Skips discussions whose domain has no hub.
    """
    nodes: list[Node] = []
    edges: list[Edge] = []
    counter = 0

    for conv in conversations:
        project = conv.get("project") or ""

        hub_id = _find_domain_hub(project, domain_hub_ids)
        if hub_id is None:
            continue

        counter += 1
        node_id = f"disc_{counter}"
        nodes.append(build_discussion_node(conv, node_id))

        edges.append(
            {
                "source": hub_id,
                "target": node_id,
                "type": "has-discussion",
                "weight": 0.4,
                "color": EDGE_COLORS.get("has-discussion", "#E8943A60"),
            }
        )

    return nodes, edges


def _find_domain_hub(
    project_slug: str,
    domain_hub_ids: dict[str, str],
) -> str | None:
    """Find the best domain hub for a project slug.

    Scores each hub by how many of its key words appear in the slug.
    Returns the hub with the highest score, or the first hub as fallback.
    """
    if not project_slug or not domain_hub_ids:
        return None
    slug = _slug_lower(project_slug)

    best_id: str | None = None
    best_score = 0
    for key, hub_id in domain_hub_ids.items():
        words = [w for w in key.lower().split() if len(w) > 2]
        if not words:
            continue
        score = sum(1 for w in words if w in slug)
        if score > best_score:
            best_score = score
            best_id = hub_id

    # Fallback: assign to first hub rather than dropping
    if best_id is None and domain_hub_ids:
        best_id = next(iter(domain_hub_ids.values()))
    return best_id
