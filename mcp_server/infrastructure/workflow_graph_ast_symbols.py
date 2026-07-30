"""AST *symbol* loading for the workflow graph (ADR-0046).

Split out of ``workflow_graph_source_ast.py`` (issue #275 — that file
exceeded the 300-line cap) as its own cohesive concern: querying AP for
symbol nodes (Function/Method/Struct/...) and normalizing them into the
builder-shaped dict the workflow graph consumes.

Infrastructure layer only. No core imports.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.ap_bridge import APBridge
from mcp_server.infrastructure.workflow_graph_ast_response import as_list

# AP's node labels carrying symbol semantics. Derived from
# stage-3 tree-sitter extractors; see
# ``automatised-pipeline/src/clustering.rs`` for the canonical list.
_SYMBOL_LABELS = (
    # Core — Rust + Python (original set)
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
    # Import statements (one node per ``import`` site). AP wires every
    # file to its imports via the ``Defines_File_Import`` rel table; the
    # nodes themselves carry ``id`` (``<file>::<modpath>``), ``path``,
    # ``alias``, ``is_glob``. Loaded via a custom property mapping below
    # because imports lack ``qualified_name``.
    "Import",
)

# Labels whose nodes don't expose ``qualified_name`` / ``name``. The
# load query falls back to ``id`` / ``path`` (or whatever the node
# DOES carry) so they still flow into the graph.
_NON_QUALIFIED_LABELS = {"Import"}

# source: "Cap at 10 tails to keep the WHERE clause tractable"
# (comment in _symbol_batches_async._where_for_tails)
_MAX_WHERE_TAILS = 10


def _symbol_type_from_label(label: str) -> str:
    """Map AP's label → workflow-graph symbol_type.

    Keeps the value set small so the palette (``SYMBOL_COLORS``) stays
    compact. Every AP label from every supported language collapses
    into one of: function · method · class · module · constant.
    """
    low = label.lower()
    if low == "function":
        return "function"
    if low == "method":
        return "method"
    # All type-like constructs → class. Covers Rust (struct/enum/trait),
    # Java/Kotlin (class/interface), Swift/ObjC (protocol/extension),
    # C/C++ (union).
    if low in (
        "struct",
        "enum",
        "trait",
        "class",
        "interface",
        "protocol",
        "extension",
        "union",
    ):
        return "class"
    # Module-ish containers → module (amber).
    if low in ("module", "package", "namespace"):
        return "module"
    # Value-ish / alias-ish → constant (slate).
    if low in (
        "constant",
        "typealias",
        "typedef",
        "macro",
        "field",
        "property",
        "variable",
    ):
        return "constant"
    return low


async def symbol_batches_async(
    bridge: APBridge,
    graph_path: str,
    paths: list[str],
):
    """Yield one batch of symbol rows per AP label query (async gen).

    AP stores each symbol under its own label (Function, Method,
    Struct, Enum, Trait, Constant, TypeAlias). The qualified_name
    follows ``<relative_file>::<name>``. We query each label
    separately (LadybugDB rejects multi-label ``MATCH``). Each label's
    rows are yielded as soon as its query returns, so the consumer can
    process/discard a label's rows before the next label is queried.

    ``paths`` entries may be absolute (builder convention); AP's
    ``File.id`` and the symbol ``qualified_name`` prefix are
    repo-relative. We match by ``endswith`` so both forms work.
    """
    # Build a set of basenames and tail fragments for fast matching.
    # These are also used to construct server-side WHERE predicates so
    # Kuzu filters by file prefix rather than returning ALL symbols and
    # discarding in Python. Previously the code used a blanket
    # ``LIMIT 500`` without a WHERE clause — on a 50k-symbol codebase
    # alphabetically-early files consume the entire limit and the
    # desired file's symbols are never returned.
    # source: measured 2026-06-04 — query for consolidate.py returned 0
    #   because the first 500 Functions all start with benchmarks/* or
    #   _pipeline/*; mcp_server/handlers/* never appeared.
    path_tails: set[str] = set()
    for p in paths:
        if not p:
            continue
        path_tails.add(p)
        # e.g. /abs/root/pkg/mod.py → pkg/mod.py, mod.py
        parts = p.split("/")
        for i in range(1, len(parts)):
            path_tails.add("/".join(parts[i:]))

    # Build a Cypher WHERE predicate that filters at the Kuzu level.
    # Each tail produces one STARTS WITH predicate on qualified_name
    # (or id for Import nodes). We emit the shortest unique tails only
    # — if "pkg/mod.py" is present, "mod.py" is redundant because any
    # match for "mod.py" also matches "pkg/mod.py". Cap at 10 tails
    # to keep the WHERE clause tractable.
    def _where_for_tails(prop: str, tails: set[str]) -> str:
        if not tails:
            return ""
        # Sort longest-first so shorter redundant tails are skipped.
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

    for label in _SYMBOL_LABELS:
        # Import nodes don't carry qualified_name / name — they use
        # ``id`` (``<file>::<modpath>``) and ``path`` (the imported
        # module). Use those as the qualified_name / name surrogate.
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
        if paths:
            where = _where_for_tails(prop, path_tails)
            query = select.format(where=where)
        else:
            # Load-all mode: no filter, no limit — pull the full graph.
            query = select.format(where="")
        rows = await bridge.call(
            "query_graph",
            {"graph_path": graph_path, "query": query},
        )
        # Per-label batch: built, yielded, then dropped before the next
        # label's query runs — peak retained inside the source is one
        # label's rows, not the union across all _SYMBOL_LABELS queries.
        batch: list[dict[str, Any]] = []
        for r in as_list(rows):
            qn = r.get("qualified_name")
            if not qn:
                continue
            qn_s = str(qn)
            file_part, sep, _ = qn_s.partition("::")
            if not sep:
                continue
            # Python-side match as a secondary safeguard (the WHERE
            # clause is the primary filter; this handles edge cases
            # where a shorter tail matched a different file).
            if path_tails and not any(
                p == file_part or p.endswith(file_part) or file_part.endswith(p)
                for p in path_tails
            ):
                continue
            # Resolve file_path back to the absolute form if possible.
            abs_match = next(
                (p for p in paths if p.endswith(file_part)),
                file_part,
            )
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
        if batch:
            yield batch


async def verify_symbols_async(
    bridge: APBridge,
    graph_path: str,
    qualnames: list[str],
) -> dict[str, bool]:
    """Batch verification across every AP symbol label.

    AP has no unified ``Symbol`` label — we iterate the known set
    (Function, Method, Struct, ...). Wiki references are usually
    bare names (``WorkflowGraphBuilder``), so we widen the match:
    a qualname counts as found if any AP symbol name equals it,
    its name equals the tail, or the qualified_name endswith the
    tail (``::tail`` or ``.tail``).
    """
    out: dict[str, bool] = {q: False for q in qualnames}
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
    for q in qualnames:
        tail = q.rsplit(".", 1)[-1]
        if tail in all_short:
            out[q] = True
            continue
        for qn in all_names:
            if qn == q or qn.endswith(f"::{tail}") or qn.endswith(f".{tail}"):
                out[q] = True
                break
    return out


__all__ = [
    "_SYMBOL_LABELS",
    "_NON_QUALIFIED_LABELS",
    "_MAX_WHERE_TAILS",
    "_symbol_type_from_label",
    "symbol_batches_async",
    "verify_symbols_async",
]
