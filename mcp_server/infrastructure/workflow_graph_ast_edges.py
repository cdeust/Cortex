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
from mcp_server.infrastructure.workflow_graph_ast_response import as_list
from mcp_server.infrastructure.workflow_graph_ast_symbols import (
    _NON_QUALIFIED_LABELS,
    _SYMBOL_LABELS,
)


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

    We enumerate the known rel tables (~89 queries) and collapse them to
    the semantic kinds the builder understands. Each rel-table's rows are
    yielded as its own batch the moment its query returns, so peak rows
    retained inside the source is one rel-table's result — not the union
    across all 89 queries.
    """
    # Same path-matching strategy as ``symbol_batches_async``.
    path_tails: set[str] = set()
    for p in paths:
        if not p:
            continue
        path_tails.add(p)
        parts = p.split("/")
        for i in range(1, len(parts)):
            path_tails.add("/".join(parts[i:]))
    # Enumerate the full Cartesian product of label kinds AP could
    # have produced rel tables for. AP rejects queries against rel
    # tables that don't exist by returning empty rows, so the over-
    # enumeration is safe — it just costs extra round-trips against
    # missing tables. The narrower prior lists were the reason the
    # cortex viz showed ~4k imports instead of the tens of thousands
    # the codebase actually contains: every File→Class / File→
    # Interface / File→TypeAlias / File→Macro etc. edge was being
    # silently dropped because its rel table was never queried.
    _CALL_LABELS = ("Function", "Method", "Macro")
    _IMPORT_TARGETS = _SYMBOL_LABELS  # File can import any symbol kind
    _CONTAINER_LBLS = (
        "Struct",
        "Enum",
        "Trait",
        "Class",
        "Interface",
        "Protocol",
        "Extension",
        "Union",
    )
    _MEMBER_LBLS = ("Method", "Field", "Property", "Constant", "TypeAlias")
    calls_rels = [(s, d) for s in _CALL_LABELS for d in _CALL_LABELS]
    imports_rels = [("File", t) for t in _IMPORT_TARGETS]
    member_rels = [(s, d) for s in _CONTAINER_LBLS for d in _MEMBER_LBLS]

    def _match(file_part: str) -> bool:
        if not path_tails:
            return True
        return any(
            p == file_part or p.endswith(file_part) or file_part.endswith(p)
            for p in path_tails
        )

    async def _run_edge(
        kind: str,
        table: str,
        src_lbl: str,
        dst_lbl: str,
        has_provenance: bool,
    ) -> list[dict[str, Any]]:
        """Query AP for edges of ``kind`` in ``table`` and RETURN this
        rel-table's rows as one batch (the caller yields it, then drops
        it before the next rel-table query — bounding peak to one batch).

        ``has_provenance`` gates whether to fetch ``r.confidence`` +
        ``r.resolution_method``: Kuzu raises a Binder exception on
        missing-property access, so we only request those columns
        for rel tables the AP resolver actually annotates (Calls_*
        / Imports_* / Implements_* / Extends_* / Uses_*). Structural
        tables (HasMethod_* / Defines_*) have no such columns —
        callers default confidence to 1.0 for those kinds instead.
        """
        if src_lbl == "File":
            select_src = "src.id AS src_name"
        elif src_lbl in _NON_QUALIFIED_LABELS:
            select_src = "src.id AS src_name"
        else:
            select_src = "src.qualified_name AS src_name"
        # Import nodes (and any other ``_NON_QUALIFIED_LABELS`` kind)
        # carry ``id`` instead of ``qualified_name``. Selecting the
        # missing property would raise a Kuzu Binder exception.
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
        query = (
            f"MATCH (src:{src_lbl})-[r:{table}]->(dst:{dst_lbl}) "
            f"RETURN {select_src}, {return_tail}"
        )
        rows = await bridge.call(
            "query_graph",
            {"graph_path": graph_path, "query": query},
        )
        batch: list[dict[str, Any]] = []
        for r in as_list(rows):
            src = str(r.get("src_name") or "")
            dst = str(r.get("dst_name") or "")
            if not dst:
                continue
            # src may be a File.id (relative path) or a symbol qn.
            if src_lbl == "File":
                src_file = src
                src_qn = ""
            else:
                src_file, _, _ = src.partition("::")
                src_qn = src
            dst_file, _, _ = dst.partition("::")
            if kind == "imports":
                if not _match(src_file):
                    continue
            else:
                if not (_match(src_file) and _match(dst_file)):
                    continue
            # AP stores ``resolution_method`` wrapped in literal
            # single quotes (see ``automatised-pipeline``
            # resolver.rs:183 — ``format!("'{method}'")``), so the
            # value comes back INCLUDING quotes. Strip them here at
            # the infrastructure boundary. Remove this strip once
            # AP fixes the upstream quoting.
            conf_raw = r.get("confidence") if has_provenance else None
            try:
                confidence = float(conf_raw) if conf_raw is not None else None
            except (TypeError, ValueError):
                confidence = None
            reason_raw = r.get("reason") if has_provenance else None
            reason_str = str(reason_raw).strip("'\"") or None if reason_raw else None
            batch.append(
                {
                    "kind": kind,
                    "src_file": src_file,
                    "src_name": src_qn,
                    "dst_file": dst_file,
                    "dst_name": dst,
                    "confidence": confidence,
                    "reason": reason_str,
                }
            )
        return batch

    for s, d in calls_rels:
        yield await _run_edge("calls", f"Calls_{s}_{d}", s, d, has_provenance=True)
    for s, d in imports_rels:
        yield await _run_edge("imports", f"Imports_{s}_{d}", s, d, has_provenance=True)
    for s, d in member_rels:
        yield await _run_edge(
            "member_of", f"HasMethod_{s}_{d}", s, d, has_provenance=False
        )
    # File → Import node. AP wires every ``import`` statement to its
    # file via this rel table; counts in the tens of thousands per
    # project. Without this, the cortex viz captures only the small
    # subset that AP managed to RESOLVE to in-graph symbols (the
    # ``Imports_File_*`` tables, totalling ~5k vs ~36k actual).
    yield await _run_edge(
        "imports",
        "Defines_File_Import",
        "File",
        "Import",
        has_provenance=False,
    )
    # Type-usage edges (Method/Function uses Struct/Class/etc).
    # Captured by AP's resolver and exposed as ``Uses_<src>_<dst>``.
    _USES_SRC = ("Method", "Function")
    _USES_DST = (
        "Struct",
        "Enum",
        "Trait",
        "Class",
        "Interface",
        "Protocol",
        "Extension",
        "Union",
        "TypeAlias",
    )
    for s in _USES_SRC:
        for d in _USES_DST:
            yield await _run_edge("uses", f"Uses_{s}_{d}", s, d, has_provenance=True)


__all__ = ["edge_batches_async"]
