"""Wiki Mermaid block builders — pure, deterministic.

Renders Mermaid diagrams from typed inputs. No I/O, no LLM, no
randomness. Same input → byte-identical output (golden-test friendly).

Slice 3 surface:
    - schema_entity_wheel: one schema's top entities as a star graph
    - schema_overlap_graph: domain-wide schemas linked by shared entities
"""

from __future__ import annotations

from mcp_server.core.wiki_layout import slugify
from mcp_server.shared.similarity import jaccard_similarity

_OPEN = "```mermaid"
_CLOSE = "```"


def _wrap(body: list[str]) -> str:
    return "\n".join([_OPEN, *body, _CLOSE])


def _node_id(prefix: str, value: str) -> str:
    """Stable mermaid node id from a string."""
    return f"{prefix}_{slugify(value).replace('-', '_')}"


def _top_entities(
    entity_signature: dict[str, float], limit: int
) -> list[tuple[str, float]]:
    """Sorted by weight desc then name asc — deterministic."""
    return sorted(
        entity_signature.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )[:limit]


def schema_entity_wheel(
    schema_label: str,
    entity_signature: dict[str, float],
    *,
    limit: int = 8,
) -> str:
    """Star graph: schema in the centre, top-N entities radiating out."""
    body: list[str] = ["graph LR"]
    centre = _node_id("schema", schema_label or "unnamed")
    body.append(f'    {centre}(["{schema_label or "unnamed"}"])')
    top = _top_entities(entity_signature, limit)
    if not top:
        body.append(f"    {centre} -.-> empty([no entities])")
        return _wrap(body)
    for name, weight in top:
        node = _node_id("e", name)
        body.append(f'    {node}["{name}"]')
        body.append(f"    {centre} -- {weight:.2f} --> {node}")
    return _wrap(body)


def causal_chain_graph(
    edges: list[tuple[str, str, str]],
) -> str:
    """Directional graph for a causal chain.

    Input: list of (source_name, relationship_type, target_name). Sorted
    internally for determinism.
    """
    body: list[str] = ["graph TD"]
    if not edges:
        body.append("    empty([no edges])")
        return _wrap(body)
    sorted_edges = sorted(edges, key=lambda e: (e[0], e[2], e[1]))
    seen_nodes: set[str] = set()
    for src, _rel, tgt in sorted_edges:
        for name in (src, tgt):
            nid = _node_id("n", name)
            if nid not in seen_nodes:
                body.append(f'    {nid}["{name}"]')
                seen_nodes.add(nid)
    for src, rel, tgt in sorted_edges:
        a = _node_id("n", src)
        b = _node_id("n", tgt)
        body.append(f"    {a} -- {rel} --> {b}")
    return _wrap(body)


def schema_overlap_graph(
    schemas: list[tuple[str, str, dict[str, float]]],
    *,
    min_overlap: float = 0.3,
) -> str:
    """Graph of schemas linked by shared-entity Jaccard ≥ min_overlap.

    Input: list of (schema_id, label, entity_signature). Order is sorted
    internally by schema_id for deterministic output.
    """
    body: list[str] = ["graph LR"]
    sorted_schemas = sorted(schemas, key=lambda s: s[0])
    if not sorted_schemas:
        body.append("    empty([no schemas])")
        return _wrap(body)
    for sid, label, _sig in sorted_schemas:
        node = _node_id("s", sid)
        safe = label or sid
        body.append(f'    {node}(["{safe}"])')
    for i, (sid_a, _la, sig_a) in enumerate(sorted_schemas):
        keys_a = set(sig_a.keys())
        for sid_b, _lb, sig_b in sorted_schemas[i + 1 :]:
            overlap = jaccard_similarity(keys_a, set(sig_b.keys()))
            if overlap >= min_overlap:
                a = _node_id("s", sid_a)
                b = _node_id("s", sid_b)
                body.append(f"    {a} -- {overlap:.2f} --- {b}")
    return _wrap(body)
