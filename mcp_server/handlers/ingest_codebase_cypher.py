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
from typing import Any, AsyncIterator

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
        bool(head) and "." in head and "/" not in head and not head.endswith(code_exts)
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
    """Run a single cypher query, draining upstream byte-budget pages.

    Upstream ``query_graph`` (automatised-pipeline ≥0.4.0,
    ``do_query_graph`` in src/main.rs) bounds every response two ways:
      1. ``LIMIT 500`` is injected into any Cypher lacking a LIMIT clause
         (``limit_injected: true``) — pagination CANNOT recover rows past
         that, so every caller here MUST declare its own LIMIT.
      2. Wide rows are byte-paged: the response carries
         ``truncated: true`` + ``next_offset`` and the caller must re-call
         with ``offset=next_offset`` to drain the remaining rows.
    Ignoring (2) silently truncated ingests (~887/4669 call edges,
    2026-06-11 RCA). This function follows ``next_offset`` until
    ``truncated`` is false and returns the merged result; merged size is
    bounded by the caller's explicit LIMIT.

    Returns (result_dict, error_message). On upstream-reported errors
    (status=error), result is None and the error_message is populated.
    Transport errors raise; callers catch narrow transport classes and
    surface them as diagnostics.
    """
    merged_rows: list[Any] = []
    offset = 0
    result: dict[str, Any] | None = None
    while True:
        payload = await call_upstream(
            _UPSTREAM_SERVER,
            "query_graph",
            {"graph_path": graph_path, "query": cypher, "offset": offset},
        )
        page = normalise_mcp_payload(payload)
        if isinstance(page, dict) and page.get("status") == "error":
            return None, str(page.get("message") or "<unknown upstream error>")
        if not isinstance(page, dict):
            return None, f"unexpected payload type: {type(page).__name__}"
        result = page
        merged_rows.extend(page.get("rows") or [])
        next_offset = page.get("next_offset")
        if not page.get("truncated") or next_offset is None:
            break
        if int(next_offset) <= offset:
            # Non-advancing cursor would loop forever — upstream contract
            # violation; surface it instead of spinning.
            return None, f"non-advancing pagination cursor at offset {offset}"
        offset = int(next_offset)
    result = dict(result)
    result["rows"] = merged_rows
    return result, None


def symbol_page_stride(page_size: int) -> int:
    """Per-label row count fetched by one ``fetch_symbols_page`` call.

    Callers MUST advance ``offset`` by exactly this stride between calls.
    The previous caller advanced by ``page_size`` while each label's query
    used ``LIMIT page_size // 3`` — every window silently skipped the
    per-label rows between the two (≈2 000 of 3 645 Functions on the
    Cortex graph, 2026-06-11 RCA). Keeping the stride and the LIMIT in
    one function makes that mismatch impossible.
    """
    return max(1, page_size // len(_SYMBOL_LABELS))


async def fetch_symbols_total(
    graph_path: str,
) -> int | None:
    """Return the total symbol count across all three label types.

    Runs three cheap ``COUNT(*)`` Cypher queries (one per label) and sums
    the results. This is used as the ``total`` denominator for within-stage
    progress so the entity stage shows a determinate fraction.

    Returns None when any query fails — callers must treat None as
    indeterminate and fall back to textual movement.
    """
    total = 0
    for label, _ in _SYMBOL_LABELS:
        cypher = f"MATCH (n:{label}) RETURN COUNT(n) AS c"
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS:
            return None
        if err is not None or result is None:
            return None
        rows = result.get("rows") or []
        if not rows or not rows[0]:
            return None
        try:
            total += int(rows[0][0])
        except (TypeError, ValueError, IndexError):
            return None
    return total


async def fetch_symbols_page(
    graph_path: str,
    offset: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch one page of symbols starting at per-label row ``offset``.

    ``offset`` is a PER-LABEL row offset: each of the three label queries
    runs ``SKIP offset LIMIT symbol_page_stride(page_size)``, so one call
    returns at most ``page_size`` rows across labels and the JSON-RPC
    payload per call stays bounded regardless of total corpus size.
    ``ORDER BY qualified_name`` gives stable pagination across calls (no
    duplicates / gaps as long as the graph is unchanged) — provided the
    caller advances by ``symbol_page_stride(page_size)``.

    Returns ``(symbols, diagnostics)``. An empty ``symbols`` list with an
    empty ``diagnostics`` list means every label is exhausted (end of
    data); labels exhaust independently, so a non-empty page may already
    contain fewer than ``page_size`` rows.
    """
    rows: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    per_label = symbol_page_stride(page_size)
    for label, kind in _SYMBOL_LABELS:
        cypher = (
            f"MATCH (n:{label}) "
            "RETURN n.qualified_name AS qualified_name, n.name AS name, "
            "n.start_line AS start_line, n.end_line AS end_line, "
            "n.visibility AS visibility "
            "ORDER BY n.qualified_name "
            f"SKIP {offset} LIMIT {per_label}"
        )
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS as exc:
            diagnostics.append(f"{label}@{offset}: {type(exc).__name__}: {exc}")
            continue
        if err is not None:
            diagnostics.append(f"{label}@{offset}: {err}")
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
                    "file": None,
                    "start_line": record.get("start_line"),
                    "end_line": record.get("end_line"),
                    "visibility": record.get("visibility"),
                }
            )
    return rows, diagnostics


_CALL_SRC_LABELS: tuple[str, ...] = ("Function", "Method", "Struct")


async def iter_call_edges(
    graph_path: str,
    page_size: int,
) -> "AsyncIterator[tuple[list[tuple[str, str]], list[str]]]":
    """Stream call edges page by page, ``(batch, diagnostics)`` per yield.

    Pages each source-label query via SKIP/LIMIT so no full edge list (nor an
    O(total_edges) dedup ``seen`` set) is ever held — duplicate edges are
    deduped server-side by the staging ``ON CONFLICT DO NOTHING``, and dangling
    endpoints by the JOIN. Kuzu is read-only during ingest, so OFFSET paging is
    drift-safe. Self-edges are dropped. Peak RAM is one page.
    """
    for src_label in _CALL_SRC_LABELS:
        offset = 0
        while True:
            cypher = (
                f"MATCH (a:{src_label})-[]->(b:Function|Method|Struct) "
                f"RETURN a.qualified_name AS src, b.qualified_name AS dst "
                f"SKIP {offset} LIMIT {page_size}"
            )
            try:
                result, err = await _run_query(graph_path, cypher)
            except _TRANSPORT_ERRORS as exc:
                yield (
                    [],
                    [f"call-edges/{src_label}@{offset}: {type(exc).__name__}: {exc}"],
                )
                break
            if err is not None:
                yield [], [f"call-edges/{src_label}@{offset}: {err}"]
                break
            rows = result.get("rows") or []
            batch: list[tuple[str, str]] = []
            for row in rows:
                if len(row) < 2:
                    continue
                src, dst = row[0], row[1]
                if src and dst and src != dst:
                    batch.append((src, dst))
            yield batch, []
            if len(rows) < page_size:
                break
            offset += page_size


async def iter_containment_edges(
    graph_path: str,
    known_files: set[str],
    page_size: int,
) -> "AsyncIterator[tuple[list[tuple[str, str]], list[str]]]":
    """Stream (file_path, symbol_qn) containment edges page by page.

    Pages via SKIP/LIMIT — no full list, no ``seen`` set. ``known_files``
    (bounded by file count) filters to ingested files; dangling symbol
    endpoints are dropped by the staging JOIN. Peak RAM is one page.
    """
    if not known_files:
        return
    offset = 0
    while True:
        cypher = (
            "MATCH (f:File)-[]->(n:Function|Method|Struct) "
            "RETURN f.path AS file_path, n.qualified_name AS qn "
            f"SKIP {offset} LIMIT {page_size}"
        )
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS as exc:
            yield [], [f"file-containment@{offset}: {type(exc).__name__}: {exc}"]
            return
        if err is not None:
            yield [], [f"file-containment@{offset}: {err}"]
            return
        rows = result.get("rows") or []
        batch: list[tuple[str, str]] = []
        for row in rows:
            if len(row) < 2:
                continue
            f, qn = row[0], row[1]
            if f and qn and f in known_files:
                batch.append((f, qn))
        yield batch, []
        if len(rows) < page_size:
            return
        offset += page_size


# File-fetch page size. A LIMIT-less Cypher gets `LIMIT 500` injected
# upstream (QUERY_GRAPH_ROW_LIMIT, automatised-pipeline src/main.rs), which
# silently capped fetch_files at 500/1233 files (2026-06-11 RCA). Paging with
# an explicit SKIP/LIMIT below that injection threshold keeps each JSON-RPC
# payload bounded AND visits every File node.
_FILE_PAGE_SIZE: int = 500


async def fetch_files(
    graph_path: str,
    limit: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Pull every File node so file-level containment edges resolve.

    ``limit=None`` ⇒ pull all via an explicit SKIP/LIMIT paging loop
    (``ORDER BY f.path`` gives a stable order; Kuzu is read-only during
    ingest, so OFFSET paging is drift-safe); ``limit>0`` ⇒ cap.
    Returns (files, diagnostics).
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page_limit = _FILE_PAGE_SIZE
        if limit is not None and limit > 0:
            remaining = limit - len(rows)
            if remaining <= 0:
                break
            page_limit = min(page_limit, remaining)
        cypher = (
            "MATCH (f:File) "
            "RETURN f.path AS path, f.name AS name, f.extension AS extension, "
            "f.size_bytes AS size_bytes "
            "ORDER BY f.path "
            f"SKIP {offset} LIMIT {page_limit}"
        )
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS as exc:
            return rows, [f"files@{offset}: {type(exc).__name__}: {exc}"]
        if err is not None:
            return rows, [f"files@{offset}: {err}"]
        page_rows = result.get("rows") or []
        for row in page_rows:
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
        if len(page_rows) < page_limit:
            break
        offset += page_limit
    return rows, []


async def fetch_process_symbols(
    graph_path: str,
    entry_point_id: str,
    limit: int,
) -> tuple[list[str], list[str]]:
    """Fetch qualified names of symbols participating in one process.

    Membership edges are ``(:Function|Method)-[:ParticipatesIn_<Label>_Process]->
    (:Process)`` (automatised-pipeline src/clustering/process.rs,
    ``persist_participates_in``); the process is keyed by its unique
    ``entry_point_id`` (one traced process per entry point). Returns
    (qualified_names, diagnostics).
    """
    qns: list[str] = []
    diagnostics: list[str] = []
    esc = entry_point_id.replace("'", "\\'")
    for label in ("Function", "Method"):
        cypher = (
            f"MATCH (n:{label})-[:ParticipatesIn_{label}_Process]->(p:Process) "
            f"WHERE p.entry_point_id = '{esc}' "
            "RETURN n.qualified_name AS qn "
            f"ORDER BY n.qualified_name LIMIT {limit}"
        )
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS as exc:
            diagnostics.append(f"process-symbols/{label}: {type(exc).__name__}: {exc}")
            continue
        if err is not None:
            diagnostics.append(f"process-symbols/{label}: {err}")
            continue
        for row in result.get("rows") or []:
            if row and row[0]:
                qns.append(row[0])
    return qns[:limit], diagnostics
