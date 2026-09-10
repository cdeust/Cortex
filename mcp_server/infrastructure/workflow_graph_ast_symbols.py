"""Infrastructure layer only. No core imports.

source: ADR-0633"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.ap_bridge import APBridge
from mcp_server.infrastructure.workflow_graph_ast_response import (
    as_list,
    build_path_tails,
)

# source: ADR-0633
_SYMBOL_LABELS = (
    # source: ADR-0633
    "Function",
    "Method",
    "Struct",
    "Enum",
    "Trait",
    "Constant",
    "TypeAlias",
    # JVM family — Java, Kotlin
    "Class",
    "Interface",
    "Field",
    "Property",
    # Swift / ObjC family
    "Protocol",
    "Extension",
    # C / C++
    "Union",
    "Typedef",
    "Macro",
    # Go / general
    "Module",
    "Package",
    "Namespace",
    "Variable",
    # source: ADR-0633
    "Import",
)

# source: ADR-0633
_NON_QUALIFIED_LABELS = {"Import"}

# source: ADR-0633  # noqa: ERA001
_MAX_WHERE_TAILS = 10


_LABEL_TO_SYMBOL_TYPE: dict[str, str] = {
    "function": "function",
    "method": "method",
    # All type-like constructs → class. Covers Rust (struct/enum/trait),
    # Java/Kotlin (class/interface), Swift/ObjC (protocol/extension), C/C++
    # (union).
    **dict.fromkeys(
        (
            "struct",
            "enum",
            "trait",
            "class",
            "interface",
            "protocol",
            "extension",
            "union",
        ),
        "class",
    ),
    # Module-ish containers → module (amber).
    **dict.fromkeys(("module", "package", "namespace"), "module"),
    # Value-ish / alias-ish → constant (slate).
    **dict.fromkeys(
        ("constant", "typealias", "typedef", "macro", "field", "property", "variable"),
        "constant",
    ),
}


def _symbol_type_from_label(label: str) -> str:
    """Map AP's label → workflow-graph symbol_type via
    ``_LABEL_TO_SYMBOL_TYPE`` (keeps the palette — ``SYMBOL_COLORS`` —
    compact). An unmapped label (e.g. ``Import``) passes through
    lowercased, unchanged."""
    low = label.lower()
    return _LABEL_TO_SYMBOL_TYPE.get(low, low)


def _where_for_tails(prop: str, tails: set[str]) -> str:
    """Build a Cypher WHERE predicate that filters at the Kuzu level.

    source: ADR-0633"""
    if not tails:
        return ""
    sorted_tails = sorted(tails, key=len, reverse=True)
    kept: list[str] = []
    for t in sorted_tails:
        if any(t == k or k.endswith(t) for k in kept):
            continue  # already covered by a longer tail
        kept.append(t)
        if len(kept) >= _MAX_WHERE_TAILS:
            break
    escaped = [t.replace("'", "\\'") for t in kept]
    preds = " OR ".join(f"{prop} STARTS WITH '{t}::'" for t in escaped)
    return f" WHERE {preds}"


def _build_symbol_query(label: str, paths: list[str], path_tails: set[str]) -> str:
    """Construct the per-label Cypher query.

    Import nodes don't carry qualified_name/name — they use ``id``
    (``<file>::<modpath>``) and ``path`` (the imported module) as the
    qualified_name/name surrogate. Empty ``paths`` means load-all mode:
    no WHERE filter, pull the full graph.
    """
    if label in _NON_QUALIFIED_LABELS:
        prop = "s.id"
        select = (
            f"MATCH (s:{label})"
            "{where}"
            " RETURN s.id   AS qualified_name,"
            "        s.path AS name"
        )
    else:
        prop = "s.qualified_name"
        select = (
            f"MATCH (s:{label})"
            "{where}"
            " RETURN s.qualified_name AS qualified_name,"
            "        s.name           AS name"
        )
    if not paths:
        return select.format(where="")
    return select.format(where=_where_for_tails(prop, path_tails))


def _parse_symbol_batch(
    rows: Any,
    label: str,
    path_tails: set[str],
    paths: list[str],
) -> list[dict[str, Any]]:
    """Normalise one label query's rows into workflow-graph symbol dicts.

    The ``path_tails`` re-check here is a Python-side secondary safeguard
    (the WHERE clause built by ``_build_symbol_query`` is the primary
    filter; this handles edge cases where a shorter tail matched a
    different file).
    """
    batch: list[dict[str, Any]] = []
    for r in as_list(rows):
        qn = r.get("qualified_name")
        if not qn:
            continue
        qn_s = str(qn)
        file_part, sep, _ = qn_s.partition("::")
        if not sep:
            continue
        if path_tails and not any(
            p == file_part or p.endswith(file_part) or file_part.endswith(p)
            for p in path_tails
        ):
            continue
        # Resolve file_path back to the absolute form if possible.
        abs_match = next((p for p in paths if p.endswith(file_part)), file_part)
        batch.append(
            {
                "file_path": abs_match,
                "qualified_name": qn_s,
                "symbol_type": _symbol_type_from_label(label),
                "signature": None,
                "language": None,
                "line": None,
            }
        )
    return batch


async def symbol_batches_async(
    bridge: APBridge,
    graph_path: str,
    paths: list[str],
):
    """Yield one batch of symbol rows per AP label query (async gen).

        ``paths`` entries may be absolute (builder convention); AP's
        ``File.id`` and the symbol ``qualified_name`` prefix are
        repo-relative — ``build_path_tails``/``_where_for_tails`` match by
        tail so both forms work, both server-side (WHERE) and as a Python
        safeguard (``_parse_symbol_batch``).

    source: ADR-0633"""
    path_tails = build_path_tails(paths)
    for label in _SYMBOL_LABELS:
        query = _build_symbol_query(label, paths, path_tails)
        rows = await bridge.call(
            "query_graph",
            {"graph_path": graph_path, "query": query},
        )
        batch = _parse_symbol_batch(rows, label, path_tails, paths)
        if batch:
            yield batch


async def _collect_all_symbol_names(
    bridge: APBridge, graph_path: str
) -> tuple[list[str], list[str]]:
    """Query every AP symbol label once; return ``(qualified_names,
    short_names)`` across all of them — the corpus ``verify_symbols_async``
    matches candidate qualnames against."""
    all_names: list[str] = []
    all_short: list[str] = []
    for label in _SYMBOL_LABELS:
        query = (
            f"MATCH (s:{label}) "
            "RETURN DISTINCT s.qualified_name AS qualified_name, "
            "                s.name           AS name"
        )
        rows = await bridge.call(
            "query_graph",
            {"graph_path": graph_path, "query": query},
        )
        for r in as_list(rows):
            qn = str(r.get("qualified_name") or "")
            nm = str(r.get("name") or "")
            if qn:
                all_names.append(qn)
            if nm:
                all_short.append(nm)
    return all_names, all_short


def _qualname_matches(q: str, all_names: list[str], all_short: list[str]) -> bool:
    """Widened match: a qualname counts as found if any AP symbol name
    equals it, its short name equals the tail, or the qualified_name
    endswith the tail (``::tail`` or ``.tail``) — wiki references are
    usually bare names (``WorkflowGraphBuilder``)."""
    tail = q.rsplit(".", 1)[-1]
    if tail in all_short:
        return True
    return any(
        qn == q or qn.endswith(f"::{tail}") or qn.endswith(f".{tail}")
        for qn in all_names
    )


async def verify_symbols_async(
    bridge: APBridge,
    graph_path: str,
    qualnames: list[str],
) -> dict[str, bool]:
    """Batch verification across every AP symbol label.

    AP has no unified ``Symbol`` label — ``_collect_all_symbol_names``
    iterates the known set once and ``_qualname_matches`` checks each
    candidate against that corpus (see its docstring for the match rule).
    """
    all_names, all_short = await _collect_all_symbol_names(bridge, graph_path)
    return {q: _qualname_matches(q, all_names, all_short) for q in qualnames}


__all__ = [
    "_SYMBOL_LABELS",
    "_NON_QUALIFIED_LABELS",
    "_MAX_WHERE_TAILS",
    "_symbol_type_from_label",
    "symbol_batches_async",
    "verify_symbols_async",
]
