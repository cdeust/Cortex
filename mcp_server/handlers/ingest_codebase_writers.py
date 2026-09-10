"""Cortex-side projection for ingest_codebase — pure row builders.

Projects the upstream graph projection (symbols, files, edges) into the row
tuples the streaming staging sinks COPY into PostgreSQL. These functions are
PURE (no I/O): the handler (composition root) drives them through
``StagingResolveSink`` / ``BackpressurePipeline`` so ids resolve server-side
and no ``name -> id`` map is ever held in Python.

source: ADR-0404"""

from __future__ import annotations

from typing import Any

from mcp_server.shared.entity_canonical import canonicalize_entity_name

# Row tuple shapes (column order matches the staging COPY in
# staging_resolve_sink): entity = (name, type, domain, heat);
# edge = (src_name, dst_name, rel_type, weight, domain). Edges carry the
# domain so endpoint resolution joins within ONE domain — entities dedup
# per (name, domain), and an unscoped name JOIN would fan out across
# domains.
EntityRow = tuple[str, str, str, float]
EdgeRow = tuple[str, str, str, float, str]

_SYMBOL_HEAT = 0.8
_FILE_HEAT = 0.6


def _symbol_name(sym: dict[str, Any]) -> str | None:
    qn = sym.get("qualified_name") or sym.get("name")
    return qn or None


def symbol_entity_row(sym: dict[str, Any], domain: str) -> EntityRow | None:
    """Project a symbol into an entity row, or None if it has no name."""
    qn = _symbol_name(sym)
    if not qn:
        return None
    return (
        canonicalize_entity_name(qn),
        sym.get("kind", "symbol"),
        domain,
        _SYMBOL_HEAT,
    )


def file_entity_row(f: dict[str, Any], domain: str) -> EntityRow | None:
    """Project a file into an entity row, or None if it has no path."""
    path = f.get("path")
    if not path:
        return None
    return (path, "file", domain, _FILE_HEAT)


def call_edge_row(edge: tuple[str, str], domain: str) -> EdgeRow | None:
    """Project a (caller_qn, callee_qn) call edge into an edge row.

    Self-edges are dropped (a symbol calling itself is graph noise here).
    """
    src, dst = edge
    if not src or not dst:
        return None
    csrc, cdst = canonicalize_entity_name(src), canonicalize_entity_name(dst)
    if csrc == cdst:
        return None
    return (csrc, cdst, "calls", 1.0, domain)


def containment_edge_row(edge: tuple[str, str], domain: str) -> EdgeRow | None:
    """Project a (file_path, symbol_qn) containment edge into an edge row."""
    file_path, symbol_qn = edge
    if not file_path or not symbol_qn:
        return None
    return (file_path, canonicalize_entity_name(symbol_qn), "contains", 1.0, domain)
