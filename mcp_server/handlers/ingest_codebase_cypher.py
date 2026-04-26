"""Cypher fetchers for ingest_codebase.

Pure data extraction from the upstream Kuzu graph via the
``query_graph`` MCP tool. No I/O against Cortex's own stores —
that's the writers' job.

Schema (probed 2026-04-25 against ai-automatised-pipeline graph):
  - Function/Method/Struct nodes: id, name, qualified_name,
    start_line, end_line, visibility, is_async (Method also has
    receiver_type).
  - File node: id, path, name, extension, size_bytes.
  - Relationships are untyped in this Kuzu schema; we walk via
    label-restricted patterns.

File attribution is **derived from the (:File)-[]->(:symbol)
containment edges**, not from string-splitting qualified_name. The
containment edges are language-agnostic — whatever the upstream
indexer produces for Rust, Python, or TypeScript, the File→symbol
relationships are the source of truth. ``file_path_from_qn`` exists
only as a last-resort fallback when a symbol has no containment
edge in the graph (orphan symbols, virtual symbols).
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.handlers.ingest_helpers import call_upstream, normalise_mcp_payload

logger = logging.getLogger(__name__)

_UPSTREAM_SERVER = "codebase"

_SYMBOL_LABELS: tuple[tuple[str, str], ...] = (
    ("Function", "Function"),
    ("Method", "Method"),
    ("Struct", "Struct"),
)

# Errors we expect from a misbehaving upstream/MCP transport. Anything
# outside this set is a programming error and must propagate so the
# handler's outer error path runs (Liskov/Dijkstra audits Apr-2026).
_TRANSPORT_ERRORS: tuple[type[Exception], ...] = (
    McpConnectionError,
    ValueError,
    KeyError,
    TypeError,
)


def file_path_from_qn(qn: str) -> list[str]:
    """Last-resort heuristic: derive plausible file-path candidates
    from a qualified_name when the graph has no (:File)-[]->(:symbol)
    edge for it.

    Returns a list of candidate paths (zero or more), in priority
    order. Callers MUST validate each candidate against the
    known-files set before trusting it — the qn alone cannot
    distinguish a Python module from a Rust crate path.

    Heuristics applied (priority order):
      1. ``<path/with/extension>::<sym>`` — head already a file path
         (Python via `<file>::<sym>`, e.g. ``deps/aiofile/aio.py::AIOFile``).
      2. ``<dotted.module>::<sym>`` — convert dots to slashes and
         append ``.py`` (e.g. ``my.pkg.mod::C`` ⇒ ``my/pkg/mod.py``).
      3. ``<a::b::c>::<sym>`` — convert ``::`` separators to slashes
         and append ``.py`` (Rust-style module path used by some
         Python indexers, e.g. ``mcp_server::handlers::x::handler``
         ⇒ ``mcp_server/handlers/x.py`` or ``mcp_server/handlers/x/handler.py``).
      4. Same as (3) but treating the trailing segment as a method
         on a class — drop the last two segments and use ``.py``.

    Returns an empty list when the qn is empty or has no ``::``.
    """
    if not qn or "::" not in qn:
        return []
    candidates: list[str] = []
    code_exts = (".py", ".ts", ".tsx", ".rs", ".js")
    head = qn.split("::", 1)[0]
    head_is_path = bool(head) and ("/" in head or head.endswith(code_exts))
    head_is_dotted_module = (
        bool(head)
        and "." in head
        and "/" not in head
        and not head.endswith(code_exts)
    )

    # (1) head already looks like a file path — trust it as-is.
    if head_is_path:
        candidates.append(head)
        return candidates

    # (2) dotted-module head (classic Python ``pkg.mod::Sym``).
    if head_is_dotted_module:
        candidates.append(head.replace(".", "/") + ".py")
        return candidates

    # (3,4) Rust-style ``a::b::c::sym`` module path. Try progressively
    # shorter prefixes so both ``module::function`` (drop 1) and
    # ``module::Class::method`` (drop 2) resolve.
    parts = qn.split("::")
    for drop in (1, 2, 3):
        if len(parts) - drop < 1:
            break
        prefix = parts[: len(parts) - drop]
        if not prefix:
            continue
        cand = "/".join(prefix) + ".py"
        if cand not in candidates:
            candidates.append(cand)

    return candidates


async def _run_query(
    graph_path: str, cypher: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Run a single cypher query. Returns (result_dict, error_message).

    On upstream-reported errors (status=error), result is None and the
    error_message is populated. On transport errors, raises — except
    the caller catches narrow transport-class exceptions and returns
    them as diagnostics.
    """
    payload = await call_upstream(
        _UPSTREAM_SERVER,
        "query_graph",
        {"graph_path": graph_path, "query": cypher},
    )
    result = normalise_mcp_payload(payload)
    if isinstance(result, dict) and result.get("status") == "error":
        return None, str(result.get("message") or "<unknown upstream error>")
    if not isinstance(result, dict):
        return None, f"unexpected payload type: {type(result).__name__}"
    return result, None


async def fetch_top_symbols(
    graph_path: str,
    limit: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Enumerate symbols across Function/Method/Struct.

    With ``limit=None`` (default) pulls every symbol with stable
    ``ORDER BY qualified_name``. With ``limit>0``, ranks by line span
    and caps each label proportionally.

    Returns (symbols, diagnostics). Diagnostics is a list of one-line
    error strings for queries that failed; an empty list means every
    sub-query succeeded.
    """
    rows: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    per_label = (
        max(1, limit // len(_SYMBOL_LABELS))
        if limit is not None and limit > 0
        else None
    )
    for label, kind in _SYMBOL_LABELS:
        clauses = [
            f"MATCH (n:{label})",
            (
                "RETURN n.qualified_name AS qualified_name, n.name AS name, "
                "n.start_line AS start_line, n.end_line AS end_line, "
                "n.visibility AS visibility"
            ),
        ]
        if per_label is not None:
            clauses.append("ORDER BY (n.end_line - n.start_line) DESC")
            clauses.append(f"LIMIT {per_label}")
        else:
            clauses.append("ORDER BY n.qualified_name")
        cypher = " ".join(clauses)
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS as exc:
            diagnostics.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        if err is not None:
            diagnostics.append(f"{label}: {err}")
            continue
        columns = result.get("columns") or [
            "qualified_name",
            "name",
            "start_line",
            "end_line",
            "visibility",
        ]
        for row in result.get("rows") or []:
            record = dict(zip(columns, row))
            qn = record.get("qualified_name") or record.get("name")
            if not qn:
                continue
            rows.append(
                {
                    "qualified_name": qn,
                    "name": record.get("name") or qn,
                    "kind": kind,
                    # ``file`` is intentionally left unset here. The
                    # composition root assigns it from the
                    # (:File)-[]->(:symbol) containment edges, which
                    # are language-agnostic. file_path_from_qn is a
                    # last-resort fallback for orphans only.
                    "file": None,
                    "start_line": record.get("start_line"),
                    "end_line": record.get("end_line"),
                    "visibility": record.get("visibility"),
                }
            )
    if limit is not None and limit > 0:
        rows = rows[:limit]
    return rows, diagnostics


async def fetch_call_edges(
    graph_path: str,
    known: set[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pull every call edge whose endpoints are in ``known``.

    Pushes the target-label filter server-side via Kuzu's label-OR
    pattern so Function→Process / Function→Community noise doesn't
    cross the wire. Returns (edges, diagnostics).
    """
    if not known:
        return [], []
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    diagnostics: list[str] = []
    for src_label in ("Function", "Method", "Struct"):
        cypher = (
            f"MATCH (a:{src_label})-[]->(b:Function|Method|Struct) "
            f"RETURN a.qualified_name AS src, b.qualified_name AS dst"
        )
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS as exc:
            diagnostics.append(f"call-edges/{src_label}: {type(exc).__name__}: {exc}")
            continue
        if err is not None:
            diagnostics.append(f"call-edges/{src_label}: {err}")
            continue
        for row in result.get("rows") or []:
            if len(row) < 2:
                continue
            src, dst = row[0], row[1]
            if not src or not dst:
                continue
            if src not in known or dst not in known or src == dst:
                continue
            key = (src, dst)
            if key in seen:
                continue
            seen.add(key)
            edges.append(key)
    return edges, diagnostics


async def fetch_file_containment(
    graph_path: str,
    known_files: set[str],
    known_symbols: set[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pull (file_path, symbol_qn) containment edges.

    Single label-OR query (push-down) instead of three round-trips.
    Returns (edges, diagnostics).
    """
    if not known_files or not known_symbols:
        return [], []
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    diagnostics: list[str] = []
    cypher = (
        "MATCH (f:File)-[]->(n:Function|Method|Struct) "
        "RETURN f.path AS file_path, n.qualified_name AS qn"
    )
    try:
        result, err = await _run_query(graph_path, cypher)
    except _TRANSPORT_ERRORS as exc:
        diagnostics.append(f"file-containment: {type(exc).__name__}: {exc}")
        return edges, diagnostics
    if err is not None:
        diagnostics.append(f"file-containment: {err}")
        return edges, diagnostics
    for row in result.get("rows") or []:
        if len(row) < 2:
            continue
        f, qn = row[0], row[1]
        if not f or not qn:
            continue
        if f not in known_files or qn not in known_symbols:
            continue
        key = (f, qn)
        if key in seen:
            continue
        seen.add(key)
        edges.append(key)
    return edges, diagnostics


async def fetch_files(
    graph_path: str,
    limit: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Pull every File node so file-level containment edges resolve.

    ``limit=None`` ⇒ pull all (matches fetch_top_symbols semantics);
    ``limit>0`` ⇒ cap server-side. Returns (files, diagnostics).
    """
    clauses = [
        "MATCH (f:File)",
        (
            "RETURN f.path AS path, f.name AS name, f.extension AS extension, "
            "f.size_bytes AS size_bytes"
        ),
        "ORDER BY f.path",
    ]
    if limit is not None and limit > 0:
        clauses.append(f"LIMIT {limit}")
    cypher = " ".join(clauses)
    try:
        result, err = await _run_query(graph_path, cypher)
    except _TRANSPORT_ERRORS as exc:
        return [], [f"files: {type(exc).__name__}: {exc}"]
    if err is not None:
        return [], [f"files: {err}"]
    rows: list[dict[str, Any]] = []
    for row in result.get("rows") or []:
        if len(row) < 1 or not row[0]:
            continue
        rows.append(
            {
                "path": row[0],
                "name": row[1] if len(row) > 1 else None,
                "extension": row[2] if len(row) > 2 else None,
                "size_bytes": row[3] if len(row) > 3 else None,
            }
        )
    return rows, []
