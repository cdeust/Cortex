"""Cypher fetchers for the ingest_codebase docs-content pass (INC5.3 / D6).

source: ADR-0406"""

from __future__ import annotations

from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.handlers.ingest_helpers import call_upstream, normalise_mcp_payload

_UPSTREAM_SERVER = "codebase"

# Same transport-error contract as ingest_codebase_cypher._TRANSPORT_ERRORS —
# anything outside this set is a programming error and must propagate.
_TRANSPORT_ERRORS: tuple[type[Exception], ...] = (
    McpConnectionError,
    ValueError,
    KeyError,
    TypeError,
)

# source: ADR-0406
DOC_EXTENSIONS: tuple[str, ...] = ("md", "markdown", "mdx")

# source: ADR-0406
_PAGE_SIZE: int = 500

# source: ADR-0406
_PAIR_ROW_ARITY = 2


def _optional_col(row: list, idx: int) -> Any:
    """Positional column value, or None when the paged row is too short."""
    return row[idx] if len(row) > idx else None


async def _run_query(graph_path: str, cypher: str) -> tuple[dict[str, Any], str | None]:
    """One Cypher query, following upstream's byte-budget pagination.

    source: ADR-0406"""
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
            return {}, str(page.get("message") or "<unknown upstream error>")
        if not isinstance(page, dict):
            return {}, f"unexpected payload type: {type(page).__name__}"
        result = page
        merged_rows.extend(page.get("rows") or [])
        next_offset = page.get("next_offset")
        if not page.get("truncated") or next_offset is None:
            break
        if int(next_offset) <= offset:
            return {}, f"non-advancing pagination cursor at offset {offset}"
        offset = int(next_offset)
    result = dict(result)
    result["rows"] = merged_rows
    return result, None


def _doc_extension_filter() -> str:
    quoted = ", ".join(f"'{ext}'" for ext in DOC_EXTENSIONS)
    return f"f.extension IN [{quoted}]"


async def fetch_doc_files(graph_path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Pull every Markdown-family File node (path/name/extension/size_bytes).

    Paginated the same way ``ingest_codebase_cypher.fetch_files`` is —
    ``ORDER BY f.path`` gives stable SKIP/LIMIT pagination on a read-only
    graph (AP's graph is rebuilt, not mutated, between ingests). Returns
    ``(files, diagnostics)``.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        cypher = (
            "MATCH (f:File) WHERE " + _doc_extension_filter() + " "
            "RETURN f.path AS path, f.name AS name, f.extension AS extension, "
            "f.size_bytes AS size_bytes "
            "ORDER BY f.path "
            f"SKIP {offset} LIMIT {_PAGE_SIZE}"
        )
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS as exc:
            return rows, [f"doc-files@{offset}: {type(exc).__name__}: {exc}"]
        if err is not None:
            return rows, [f"doc-files@{offset}: {err}"]
        page_rows = result.get("rows") or []
        for row in page_rows:
            if len(row) < 1 or not row[0]:
                continue
            rows.append(
                {
                    "path": row[0],
                    "name": _optional_col(row, 1),
                    "extension": _optional_col(row, 2),
                    "size_bytes": _optional_col(row, 3),
                }
            )
        if len(page_rows) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows, []


async def fetch_doc_references(
    graph_path: str,
    known_doc_paths: set[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pull References_File_File edges whose SOURCE is a known Markdown doc.

    source: ADR-0406"""
    if not known_doc_paths:
        return [], []
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    offset = 0
    while True:
        cypher = (
            "MATCH (a:File)-[:References_File_File]->(b:File) "
            "RETURN a.path AS src, b.path AS dst "
            f"SKIP {offset} LIMIT {_PAGE_SIZE}"
        )
        try:
            result, err = await _run_query(graph_path, cypher)
        except _TRANSPORT_ERRORS as exc:
            return rows, [f"doc-refs@{offset}: {type(exc).__name__}: {exc}"]
        if err is not None:
            return rows, [f"doc-refs@{offset}: {err}"]
        page_rows = result.get("rows") or []
        for row in page_rows:
            if len(row) < _PAIR_ROW_ARITY or not row[0] or not row[1]:
                continue
            src, dst = row[0], row[1]
            if src == dst or src not in known_doc_paths:
                continue
            pair = (src, dst)
            if pair in seen:
                continue
            seen.add(pair)
            rows.append(pair)
        if len(page_rows) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows, []
