"""Graph-path resolution for ingest_codebase.

Encapsulates the "do we already have a Kuzu graph for this project?"
decision and the upstream ``analyze_codebase`` call that builds one
when we don't.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.handlers import ingest_provenance
from mcp_server.handlers.ingest_helpers import (
    call_upstream,
    find_cached_graph,
    memoise_graph_path,
    normalise_mcp_payload,
)
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

_UPSTREAM_SERVER = "codebase"


def silent_clean_stale_graph_slot(output_dir: str) -> None:
    """Pre-clean stale graph slots so first-time AP indexing succeeds.

    AP writes ``<output_dir>/graph`` as a directory; pre-3.14 versions
    of the same tool wrote a single LadybugDB file at the same path.
    When a user upgrades, the old file occupies the slot and AP's own
    ``rm_rf`` errors out (``Not a directory (os error 20)``).
    """
    slot = Path(output_dir).expanduser() / "graph"
    try:
        if slot.exists() and not slot.is_dir():
            slot.unlink()
    except OSError as exc:
        logger.debug("could not pre-clean stale graph slot %s: %s", slot, exc)


async def _call_analyze(project_path: str, output_dir: str, language: str) -> Any:
    return await call_upstream(
        _UPSTREAM_SERVER,
        "analyze_codebase",
        {
            "path": str(Path(project_path).expanduser().resolve()),
            "output_dir": str(Path(output_dir).expanduser().resolve()),
            "language": language,
        },
    )


async def ensure_graph(
    store: MemoryStore,
    project_path: str,
    output_dir: str,
    language: str,
    force_reindex: bool,
) -> tuple[str, dict[str, Any]]:
    """Return (graph_path, analyze_stats).

    Reuses the cached graph when available; otherwise calls upstream
    analyze_codebase and memoises the resulting graph path.

    Every call checks AP client-path version parity (ADR-0052 sec 2,
    INC5.2) exactly once, regardless of whether the graph is reused or
    freshly built — the parity check is a property of the two Cortex->AP
    client paths, not of any one ingestion run. The result rides in
    ``analyze_stats["ap_client_parity"]`` (the handler forwards this dict
    verbatim into the tool response's "analyze" field), satisfying the
    "surface in the response" half of D5's acceptance criterion; a
    genuine mismatch is additionally logged once by
    ``ingest_provenance.check_version_parity``.
    """
    parity = await ingest_provenance.check_version_parity()
    parity_dict = dataclasses.asdict(parity)

    if not force_reindex:
        cached = find_cached_graph(store, project_path)
        if cached:
            return cached, {
                "reused_cached": True,
                "graph_path": cached,
                "ap_client_parity": parity_dict,
            }

    silent_clean_stale_graph_slot(output_dir)
    payload = await _call_analyze(project_path, output_dir, language)
    result = normalise_mcp_payload(payload)
    # Self-heal: AP returns this specific error when the slot was a
    # non-directory at invocation time. Pre-clean covers the typical
    # case; the post-hoc retry covers a race where AP wrote a file
    # mid-call.
    if (
        isinstance(result, dict)
        and result.get("status") == "error"
        and "Not a directory" in str(result.get("message", ""))
    ):
        silent_clean_stale_graph_slot(output_dir)
        payload = await _call_analyze(project_path, output_dir, language)
        result = normalise_mcp_payload(payload)
    # Refuse to memoise a synthesised path on persistent upstream
    # error — that would poison the cache, since subsequent ingests
    # would skip analyze_codebase entirely and silently project an
    # empty graph (Liskov audit Apr-2026, Dijkstra audit #6).
    if isinstance(result, dict) and result.get("status") == "error":
        raise McpConnectionError(  # noqa: TRY003 — one-off message, not reused (§3.3)
            f"upstream analyze_codebase failed: {result.get('message', '<no message>')}"
        )
    graph_path = result.get("graph_path") or str(
        Path(output_dir).expanduser() / "graph"
    )
    memoise_graph_path(
        store,
        project_path,
        graph_path,
        ingest_provenance.ap_provenance_tags(parity.pool_version),
    )
    result["graph_path"] = graph_path
    result["reused_cached"] = False
    result["ap_client_parity"] = parity_dict
    return graph_path, result
