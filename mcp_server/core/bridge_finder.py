"""Cross-domain connection detection from structural edges and text analogies.

Two detection methods:
  - Structural bridges: cross-references from brain-index (explicit links)
  - Analogical bridges: regex-based extraction of analogy patterns in text
"""

from __future__ import annotations

import re
from typing import Any

_ANALOGY_RE = re.compile(
    r"(like|similar to|analogous to|reminds me of|just as|the same way)"
    r"\s+(?:a\s+)?(.{5,40})",
    re.IGNORECASE,
)


def _build_project_domain_map(profiles: dict | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not profiles or not profiles.get("domains"):
        return mapping
    for domain_id, domain in profiles["domains"].items():
        projects = domain.get("projects") or domain.get("projectIds") or []
        for project_id in projects:
            mapping[project_id] = domain_id
    return mapping


def _resolve_domain(node: dict, project_domain_map: dict[str, str]) -> str:
    project_id = node.get("projectId") or node.get("project")
    if project_id and project_id in project_domain_map:
        return project_domain_map[project_id]
    if node.get("domainId"):
        return node["domainId"]
    return "unknown"


def _extract_analogies(text: str | None, node_id: str) -> list[dict[str, str]]:
    if not text or not isinstance(text, str):
        return []
    results = []
    for match in _ANALOGY_RE.finditer(text):
        start = max(0, match.start() - 60)
        source_context = text[start : match.start()].strip()[-60:]
        results.append(
            {
                "nodeId": node_id,
                "pattern": match.group(1).lower(),
                "sourceContext": source_context,
                "targetConcept": match.group(2).strip(),
            }
        )
    return results


def _build_node_map(
    all_memories: dict,
    all_conversations: dict,
    project_domain_map: dict[str, str],
) -> dict[str, dict]:
    """Build a unified node map from memories and conversations."""
    nodes: dict[str, dict] = {}

    for id_, mem in all_memories.items():
        nodes[id_] = {
            "domainId": _resolve_domain(mem, project_domain_map),
            "body": mem.get("body") or mem.get("content") or "",
            "crossRefs": mem.get("crossRefs") or mem.get("connections") or [],
        }

    for id_, conv in all_conversations.items():
        nodes[id_] = {
            "domainId": _resolve_domain(conv, project_domain_map),
            "body": conv.get("body")
            or conv.get("summary")
            or conv.get("content")
            or "",
            "crossRefs": conv.get("crossRefs") or conv.get("connections") or [],
        }

    return nodes


def _make_pair_key(domain_a: str, domain_b: str) -> str:
    """Create a canonical key for an ordered domain pair."""
    if domain_a < domain_b:
        return f"{domain_a}|||{domain_b}"
    return f"{domain_b}|||{domain_a}"


def _accumulate_edge(
    pairs: dict[str, dict],
    from_domain: str,
    to_domain: str,
    weight: float,
    from_id: str,
    to_id: str,
) -> None:
    """Add a cross-domain edge to the pair accumulator."""
    pair_key = _make_pair_key(from_domain, to_domain)
    if pair_key not in pairs:
        parts = pair_key.split("|||")
        pairs[pair_key] = {
            "fromDomain": parts[0],
            "toDomain": parts[1],
            "totalWeight": 0,
            "edgeCount": 0,
            "examples": [],
        }
    pair = pairs[pair_key]
    pair["totalWeight"] += weight
    pair["edgeCount"] += 1
    if len(pair["examples"]) < 5:
        pair["examples"].append({"fromId": from_id, "toId": to_id})


def _collect_structural_pairs(
    nodes: dict[str, dict],
) -> dict[str, dict]:
    """Find cross-domain structural edges and aggregate by domain pair."""
    pairs: dict[str, dict] = {}

    for id_, node in nodes.items():
        from_domain = node["domainId"]
        for ref in node["crossRefs"]:
            target_id = (
                ref if isinstance(ref, str) else (ref.get("id") or ref.get("target"))
            )
            weight = ref.get("weight", 1) if isinstance(ref, dict) else 1
            target_node = nodes.get(target_id)
            if not target_node:
                continue
            to_domain = target_node["domainId"]
            if from_domain == to_domain:
                continue

            _accumulate_edge(pairs, from_domain, to_domain, weight, id_, target_id)

    return pairs


def _collect_analogies_by_domain(
    nodes: dict[str, dict],
) -> dict[str, list[dict]]:
    """Extract text analogies from all nodes, grouped by domain."""
    analogies_by_domain: dict[str, list[dict]] = {}

    for id_, node in nodes.items():
        analogies = _extract_analogies(node["body"], id_)
        if not analogies:
            continue
        domain_id = node["domainId"]
        if domain_id not in analogies_by_domain:
            analogies_by_domain[domain_id] = []
        analogies_by_domain[domain_id].extend(analogies)

    return analogies_by_domain


def _merge_structural_bridges(
    structural_pairs: dict[str, dict],
    result: dict[str, list[dict[str, Any]]],
) -> None:
    """Add structural bridge entries (both directions) into result."""
    for pair in structural_pairs.values():
        avg_weight = (
            pair["totalWeight"] / pair["edgeCount"] if pair["edgeCount"] > 0 else 0
        )
        shared = {
            "weight": avg_weight,
            "examples": pair["examples"],
            "edgeCount": pair["edgeCount"],
            "pattern": "structural-edge",
        }

        result.setdefault(pair["fromDomain"], []).append(
            {**shared, "toDomain": pair["toDomain"]}
        )
        result.setdefault(pair["toDomain"], []).append(
            {**shared, "toDomain": pair["fromDomain"]}
        )


def _merge_analogical_bridges(
    analogies_by_domain: dict[str, list[dict]],
    result: dict[str, list[dict[str, Any]]],
) -> None:
    """Add analogical bridge entries into result."""
    for domain_id, analogies in analogies_by_domain.items():
        by_pattern: dict[str, list[dict]] = {}
        for a in analogies:
            by_pattern.setdefault(a["pattern"], []).append(a)

        for pattern, items in by_pattern.items():
            result.setdefault(domain_id, []).append(
                {
                    "toDomain": "text-analogy",
                    "pattern": pattern,
                    "weight": len(items),
                    "examples": [
                        {
                            "nodeId": i["nodeId"],
                            "sourceContext": i["sourceContext"],
                            "targetConcept": i["targetConcept"],
                        }
                        for i in items[:5]
                    ],
                    "edgeCount": len(items),
                }
            )


def find_bridges(
    profiles: dict | None,
    brain_index: dict | None,
    memories: dict | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Find cross-domain bridges from structural edges and analogical text."""
    all_memories = {}
    if brain_index and brain_index.get("memories"):
        all_memories.update(brain_index["memories"])
    if memories:
        all_memories.update(memories)

    all_conversations = (brain_index or {}).get("conversations") or {}
    project_domain_map = _build_project_domain_map(profiles)

    nodes = _build_node_map(all_memories, all_conversations, project_domain_map)
    structural_pairs = _collect_structural_pairs(nodes)
    analogies_by_domain = _collect_analogies_by_domain(nodes)

    result: dict[str, list[dict[str, Any]]] = {}
    _merge_structural_bridges(structural_pairs, result)
    _merge_analogical_bridges(analogies_by_domain, result)

    return result
