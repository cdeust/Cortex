"""AST *edge* loading for the workflow graph (ADR-0046).

Split out of ``workflow_graph_source_ast.py`` (issue #275 — that file
exceeded the 300-line cap) as its own cohesive concern: querying AP's
per-label-pair rel tables (CALLS / IMPORTS / MEMBER_OF / USES) and
normalizing them into the builder-shaped edge dict.

Infrastructure layer only. No core imports.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.ap_bridge import APBridge
from mcp_server.infrastructure.workflow_graph_ast_response import (
    as_list,
    build_path_tails,
)
from mcp_server.infrastructure.workflow_graph_ast_symbols import (
    _NON_QUALIFIED_LABELS,
    _SYMBOL_LABELS,
)


# AP rejects queries against rel tables that don't exist by returning
# empty rows, so over-enumerating the full Cartesian product of label
# kinds below is safe — it just costs extra round-trips against missing
# tables. The narrower prior lists were the reason the cortex viz showed
# ~4k imports instead of the tens of thousands the codebase actually
# contains: every File→Class / File→Interface / File→TypeAlias /
# File→Macro etc. edge was being silently dropped because its rel table
# was never queried.
_CALL_LABELS = ("Function", "Method", "Macro")
_CONTAINER_LABELS = (
    "Struct",
    "Enum",
    "Trait",
    "Class",
    "Interface",
    "Protocol",
    "Extension",
    "Union",
)
_MEMBER_LABELS = ("Method", "Field", "Property", "Constant", "TypeAlias")
_USES_DST_LABELS = (*_CONTAINER_LABELS, "TypeAlias")


def _calls_and_member_rel_tables() -> list[tuple[str, str, str, str, bool]]:
    """``Calls_<Src>_<Dst>`` (Function↔Method↔Macro call edges) and
    ``HasMethod_<Parent>_<Member>`` (struct/enum/trait → member) tables."""
    out = [
        ("calls", f"Calls_{s}_{d}", s, d, True)
        for s in _CALL_LABELS
        for d in _CALL_LABELS
    ]
    out += [
        ("member_of", f"HasMethod_{s}_{d}", s, d, False)
        for s in _CONTAINER_LABELS
        for d in _MEMBER_LABELS
    ]
    return out


def _import_rel_tables() -> list[tuple[str, str, str, str, bool]]:
    """``Imports_File_<Lbl>`` (File → any symbol kind) plus the single
    ``Defines_File_Import`` table (File → Import node — AP wires every
    ``import`` statement to its file via this one; counts in the tens of
    thousands per project. Without it, cortex viz only shows the subset
    AP managed to RESOLVE to in-graph symbols, ~5k vs ~36k actual)."""
    out = [("imports", f"Imports_File_{t}", "File", t, True) for t in _SYMBOL_LABELS]
    out.append(("imports", "Defines_File_Import", "File", "Import", False))
    return out


def _uses_rel_tables() -> list[tuple[str, str, str, str, bool]]:
    """``Uses_<Src>_<Dst>`` (Method/Function uses Struct/Class/etc), from
    AP's resolver's type-usage tracking."""
    return [
        ("uses", f"Uses_{s}_{d}", s, d, True)
        for s in ("Method", "Function")
        for d in _USES_DST_LABELS
    ]


def _rel_tables_to_query() -> list[tuple[str, str, str, str, bool]]:
    """Enumerate every ``(kind, table, src_lbl, dst_lbl, has_provenance)``
    rel-table query AP could have produced (~89 total) — see
    ``_calls_and_member_rel_tables``/``_import_rel_tables``/
    ``_uses_rel_tables`` for each family's rationale."""
    return _calls_and_member_rel_tables() + _import_rel_tables() + _uses_rel_tables()


def _file_matches(file_part: str, path_tails: set[str]) -> bool:
    """True if ``file_part`` (a src/dst file fragment from an edge row)
    is one of ``path_tails`` — or ``path_tails`` is empty (no filter)."""
    if not path_tails:
        return True
    return any(
        p == file_part or p.endswith(file_part) or file_part.endswith(p)
        for p in path_tails
    )


def _build_edge_query(
    src_lbl: str, dst_lbl: str, table: str, has_provenance: bool
) -> str:
    """Construct the Cypher query for one rel-table.

    ``has_provenance`` gates whether to fetch ``r.confidence`` +
    ``r.resolution_method``: Kuzu raises a Binder exception on
    missing-property access, so we only request those columns for rel
    tables the AP resolver actually annotates (Calls_* / Imports_* /
    Implements_* / Extends_* / Uses_*). Structural tables (HasMethod_* /
    Defines_*) have no such columns — callers default confidence to 1.0
    for those kinds instead. ``_NON_QUALIFIED_LABELS`` nodes (e.g.
    Import) carry ``id`` instead of ``qualified_name``; selecting the
    missing property would raise a Kuzu Binder exception.
    """
    if src_lbl == "File" or src_lbl in _NON_QUALIFIED_LABELS:
        select_src = "src.id AS src_name"
    else:
        select_src = "src.qualified_name AS src_name"
    dst_qn = (
        "dst.id AS dst_name"
        if dst_lbl in _NON_QUALIFIED_LABELS
        else "dst.qualified_name AS dst_name"
    )
    if has_provenance:
        return_tail = (
            f"       {dst_qn}, "
            "       r.confidence       AS confidence, "
            "       r.resolution_method AS reason"
        )
    else:
        return_tail = f"       {dst_qn}"
    return (
        f"MATCH (src:{src_lbl})-[r:{table}]->(dst:{dst_lbl}) "
        f"RETURN {select_src}, {return_tail}"
    )


def _split_edge_endpoints(src: str, dst: str, src_lbl: str) -> tuple[str, str, str]:
    """Split raw src/dst names into ``(src_file, src_qn, dst_file)``.

    ``src`` is a File.id (relative path, when ``src_lbl == "File"``) or a
    symbol ``qualified_name`` (``<file>::<name>``); ``dst`` is always
    qualified_name-shaped here."""
    if src_lbl == "File":
        return src, "", dst.partition("::")[0]
    src_file, _, _ = src.partition("::")
    dst_file, _, _ = dst.partition("::")
    return src_file, src, dst_file


def _parse_provenance(
    r: dict, has_provenance: bool
) -> "tuple[float | None, str | None]":
    """Parse ``r.confidence``/``r.resolution_method`` when present.

    ``resolution_method`` comes back wrapped in literal single quotes
    (see ``ai-architect-mcp-codebase`` resolver.rs:183 —
    ``format!("'{method}'")``); stripped here at the infrastructure
    boundary. Remove this strip once AP fixes the upstream quoting.
    """
    conf_raw = r.get("confidence") if has_provenance else None
    try:
        confidence = float(conf_raw) if conf_raw is not None else None
    except (TypeError, ValueError):
        confidence = None
    reason_raw = r.get("reason") if has_provenance else None
    reason_str = str(reason_raw).strip("'\"") or None if reason_raw else None
    return confidence, reason_str


def _edge_row_to_dict(
    r: dict,
    kind: str,
    src_lbl: str,
    has_provenance: bool,
    path_tails: set[str],
) -> "dict[str, Any] | None":
    """Normalise one AP edge row into the builder-shaped dict, or ``None``
    if it should be dropped (no dst, or filtered out by ``path_tails``)."""
    src = str(r.get("src_name") or "")
    dst = str(r.get("dst_name") or "")
    if not dst:
        return None
    src_file, src_qn, dst_file = _split_edge_endpoints(src, dst, src_lbl)
    if kind == "imports":
        if not _file_matches(src_file, path_tails):
            return None
    elif not (
        _file_matches(src_file, path_tails) and _file_matches(dst_file, path_tails)
    ):
        return None
    confidence, reason_str = _parse_provenance(r, has_provenance)
    return {
        "kind": kind,
        "src_file": src_file,
        "src_name": src_qn,
        "dst_file": dst_file,
        "dst_name": dst,
        "confidence": confidence,
        "reason": reason_str,
    }


async def _run_edge(
    bridge: APBridge,
    graph_path: str,
    kind: str,
    table: str,
    src_lbl: str,
    dst_lbl: str,
    has_provenance: bool,
    path_tails: set[str],
) -> list[dict[str, Any]]:
    """Query AP for edges of ``kind`` in ``table`` and return this
    rel-table's rows as one batch (the caller yields it, then drops it
    before the next rel-table query — bounding peak to one batch)."""
    query = _build_edge_query(src_lbl, dst_lbl, table, has_provenance)
    rows = await bridge.call("query_graph", {"graph_path": graph_path, "query": query})
    batch: list[dict[str, Any]] = []
    for r in as_list(rows):
        parsed = _edge_row_to_dict(r, kind, src_lbl, has_provenance, path_tails)
        if parsed is not None:
            batch.append(parsed)
    return batch


async def edge_batches_async(
    bridge: APBridge,
    graph_path: str,
    paths: list[str],
):
    """Yield one batch of edge rows per AP rel-table query (async gen).

    AP uses per-label-pair typed rel tables (LadybugDB convention):
      * Calls_<Src>_<Dst>   for Function↔Method call edges
      * Imports_File_<Lbl>  for File → imported symbol
      * HasMethod_<Parent>_Method for struct/enum/trait → method

    ``_rel_tables_to_query`` enumerates the known rel tables (~89
    queries); each is issued via ``_run_edge`` and yielded as its own
    batch the moment its query returns, so peak rows retained inside the
    source is one rel-table's result — not the union across all 89.
    """
    path_tails = build_path_tails(paths)
    for kind, table, src_lbl, dst_lbl, has_provenance in _rel_tables_to_query():
        yield await _run_edge(
            bridge,
            graph_path,
            kind,
            table,
            src_lbl,
            dst_lbl,
            has_provenance,
            path_tails,
        )


__all__ = ["edge_batches_async"]
