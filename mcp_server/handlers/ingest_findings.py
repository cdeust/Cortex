"""Handler: ingest_findings — pull an AP findings run into Cortex's store.

Consumer, never producer (ADR-0052 D1): AP writes files under
``<output_dir>/runs/<run_id>/``; this handler reads them off disk and
writes Cortex memories/wiki. No network or MCP call to AP is made here —
the findings tools (extract_finding/refine_finding/start_verification/...)
are not in APBridge's allowlist (ap_bridge.py `_AP_TOOLS`) precisely
because this flow never needs them (D1 acceptance invariant: AP has no
PG/network client; this handler is the pull side).

Gradation (D2): verified finding (stage-2 verified:true) -> wiki page +
receipt memos (wiki.memos, digest-anchored) + memory tagged
finding,verified. Non-verified finding -> memory only, tagged
finding,hypothesis, low confidence. See ingest_findings_writers for the
write path and ingest_findings_artifacts for the on-disk parsing.

Pipeline convention (5.1b): run AP's stage-4 (``prepare_prd_input``) for
a verified finding BEFORE calling this handler if you want code
anchoring (wiki.page_sources, link_kind='finding') in the resulting wiki
page — stage-4 is optional and this handler never invokes it; without
it, ``file_paths`` is empty (not guessed from free text). This is
independent of the 'extracted_from' link (stage-1's source_path), which
is always anchored when AP set it, with no extra step required.

Cortex consumes; AP produces.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE
from mcp_server.handlers.ingest_findings_artifacts import (
    MalformedArtifact,
    load_finding,
    read_index,
)
from mcp_server.handlers.ingest_findings_resolve import resolve_output_dir
from mcp_server.handlers.ingest_findings_writers import write_finding
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store

logger = logging.getLogger(__name__)

schema = {
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Ingest an automatised-pipeline (AP) findings run into Cortex's "
        "store. Reads runs/<run_id>/ artifacts directly off disk (no "
        "network call to AP — AP never pushes, ADR-0052 D1). Verified "
        "findings (stage-2 verified:true) get a wiki page under "
        "reference/findings/, file-source links (wiki.page_sources, "
        "link_kind='finding' for code files the finding is ABOUT — run "
        "AP's stage-4 `prepare_prd_input` on the finding BEFORE ingesting "
        "if you want this anchoring, otherwise it is empty, not guessed; "
        "link_kind='extracted_from' for the source document the finding "
        "was extracted FROM, when stage-1's source_path is present — "
        "independent of stage-4), one wiki.memos row per stage-2/6/8 "
        "receipt (raw-bytes sha256 digest, re-verifiable, plus AP's own "
        "transcript_digest copied verbatim from stage-2.verified.json "
        "when present — two independent anchors: byte-exact vs AP's "
        "semantic claim), and a memory tagged finding,verified. "
        "Non-verified findings get a memory only, tagged "
        "finding,hypothesis, at low confidence — a hypothesis is not "
        "documentation. Idempotent: re-ingesting the same run does not "
        "duplicate memories, pages, page_sources, or memos. Distinct "
        "from `ingest_codebase` (symbols/files, not findings) and "
        "`ingest_prd` (a PRD document, not a findings run). Mutates "
        "memories + wiki.pages/page_sources/memos. Returns "
        "{ingested, findings_total, verified_count, hypothesis_count, "
        "results, errors}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["run_id"],
        "properties": {
            "run_id": {
                "type": "string",
                "description": "AP run_id whose runs/<run_id>/ artifacts to ingest.",
                "examples": ["20260709-143022-a1b2c3"],
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "Absolute path to the AP output_dir (parent of runs/ "
                    "and graph/). Takes precedence over graph_key. Omit to "
                    "resolve via graph_key or the known graph roster."
                ),
                "examples": ["/Users/alice/.cache/cortex/code-graphs/myapp-a1b2c3d4"],
            },
            "graph_key": {
                "type": "string",
                "description": (
                    "Project key (as used by ingest_codebase's "
                    "_code_graph:<key> memo tag) to resolve output_dir from "
                    "the last-memoised graph path. Ignored if output_dir "
                    "is given."
                ),
                "examples": ["myapp-a1b2c3d4"],
            },
        },
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ingest one AP findings run into Cortex."""
    args = args or {}
    run_id = (args.get("run_id") or "").strip()
    if not run_id:
        return {"ingested": False, "reason": "run_id is required"}

    store = _get_store()
    output_dir = resolve_output_dir(
        store,
        run_id=run_id,
        output_dir=args.get("output_dir"),
        graph_key=args.get("graph_key"),
    )
    if output_dir is None:
        return {
            "ingested": False,
            "reason": "output_dir_not_resolved",
            "detail": (
                "no output_dir given and no graph roster entry has runs/<run_id>/"
            ),
        }

    try:
        index = read_index(output_dir, run_id)
    except MalformedArtifact as exc:
        return {"ingested": False, "reason": "index_unreadable", "error": str(exc)}

    conn = store._conn
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for finding_id in sorted(index.get("findings", {})):
        try:
            finding = load_finding(output_dir, run_id, finding_id)
        except MalformedArtifact as exc:
            errors.append(f"{finding_id}: {exc}")
            continue
        try:
            results.append(write_finding(store, conn, finding))
        except Exception as exc:  # noqa: BLE001 — per-finding isolation; failure is logged and reported in errors
            logger.warning(
                "ingest_findings: finding %s write failed: %s", finding_id, exc
            )
            errors.append(f"{finding_id}: {exc}")

    conn.commit()

    verified_count = sum(1 for r in results if r["verified"])
    return {
        "ingested": True,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "findings_total": len(results),
        "verified_count": verified_count,
        "hypothesis_count": len(results) - verified_count,
        "results": results,
        "errors": errors,
    }
