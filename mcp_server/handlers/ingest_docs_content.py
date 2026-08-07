"""Docs-content pass for ``ingest_codebase`` (INC5.3, design decision D6).

D6: AP indexes every file as a ``File`` node (mode auto), documents
included, but never stores or searches their content — content indexing
belongs on Cortex's side (see the module docstring in
``ingest_docs_content_writers.py`` for the full rationale and sources).

This module is the pass's composition root: list Markdown-family
``File`` nodes from the AP graph, read each one off disk (root =
``project_path``, which the ``ingest_codebase`` handler already has —
D6's point that ``meta.json`` is not needed here), write one memory per
document, and re-project AP's own ``References_File_File`` edges as
relationships between the file entities the main ingest phases already
wrote.

Deliberately isolated from ``ingest_codebase.py``'s other phases — own
Cypher module (``ingest_docs_content_cypher.py``), own writers module
(``ingest_docs_content_writers.py``). This pass is optional (D6: "passe
optionnelle") and touches a disjoint slice of state (memories +
relationships only, no entity inserts, no streaming staging sink) from
the symbol/edge pipeline the rest of ``ingest_codebase`` drives.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp_server.handlers import ingest_docs_content_cypher as cypher
from mcp_server.handlers import ingest_docs_content_writers as writers

logger = logging.getLogger(__name__)

__all__ = ["run_docs_pass"]


async def run_docs_pass(
    store: Any,
    graph_path: str,
    project_path: str,
    domain: str,
) -> dict[str, Any]:
    """Ingest the content of every Markdown-family document in the graph.

    Precondition:  ``graph_path`` points at an already-analyzed AP graph;
                   ``project_path`` is the codebase root the handler was
                   given (``File.path`` values in the graph are relative
                   to it — verified against
                   ai-architect-mcp-codebase/src/indexer/walk.rs:237).
    Postcondition: returns counts (``docs_seen``, ``docs_written``,
                   ``docs_superseded``, ``docs_skipped``,
                   ``references_written``) plus any diagnostics;
                   re-running against an unchanged graph writes zero new
                   memories and zero new relationship rows (idempotent —
                   see ``writers.find_existing_doc_memory`` and
                   ``insert_relationship``'s ``ON CONFLICT``).
                   ``docs_superseded`` (issue #381) counts the subset of
                   ``docs_written`` where a source file changed since its
                   last capture and the stale snapshot memory was
                   version-chained forward rather than left to be served
                   as current — see ``writers.write_doc_memory``.
    Invariant:     no entity is inserted by this pass — every File node
                   (docs and binaries alike) already became an entity in
                   the caller's main entity phase; this function only
                   adds memories and relationship edges.
    """
    root = Path(project_path).expanduser().resolve()
    directory_context = str(root)
    diagnostics: list[str] = []

    doc_files, diag = await cypher.fetch_doc_files(graph_path)
    diagnostics.extend(diag)

    docs_written = 0
    docs_superseded = 0
    docs_skipped = 0
    for f in doc_files:
        rel_path = f.get("path")
        if not rel_path:
            continue
        content = writers.read_doc_content(root, rel_path)
        if content is None:
            docs_skipped += 1
            continue
        _, written, superseded = writers.write_doc_memory(
            store, domain, directory_context, rel_path, content
        )
        if written:
            docs_written += 1
        if superseded:
            docs_superseded += 1

    known_doc_paths = {f["path"] for f in doc_files if f.get("path")}
    refs, ref_diag = await cypher.fetch_doc_references(graph_path, known_doc_paths)
    diagnostics.extend(ref_diag)
    references_written = sum(
        1 for src, dst in refs if writers.write_doc_reference_edge(store, src, dst)
    )

    result: dict[str, Any] = {
        "docs_seen": len(doc_files),
        "docs_written": docs_written,
        "docs_superseded": docs_superseded,
        "docs_skipped": docs_skipped,
        "references_written": references_written,
    }
    if diagnostics:
        result["diagnostics"] = diagnostics
    return result
