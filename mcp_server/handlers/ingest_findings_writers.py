"""Writes one FindingRecord into Cortex's store (INC5.1 design D2-D4).

Gradation (D2): verified finding -> memory(tags: finding,verified) + wiki
page (draft, published like ingest_prd) + page_sources(link_kind='finding',
code files the finding is ABOUT) + page_sources(link_kind='extracted_from',
the document the finding was extracted FROM, when stage-1's source_path is
present) + one wiki.memos row per receipt. Unverified finding -> memory
only (tags: finding,hypothesis), low confidence, no page — a hypothesis is
not documentation.

Pipeline convention (5.1b): run stage-4 (``prepare_prd_input``) for a
verified finding BEFORE calling ``ingest_findings`` if you want code
anchoring (link_kind='finding') in the resulting wiki page — without it,
``file_paths`` is empty (not guessed). This is independent of
``source_path`` (link_kind='extracted_from'), which comes from stage-1
and needs no extra step.

Idempotence (D2 acceptance criterion, risk 8): every write here is keyed
by (run_id, finding_id[, stage]) and checked for existence before insert,
so re-ingesting the same run produces the same row counts. ``upsert_page``
and ``upsert_page_sources`` are already idempotent by construction
(ADR-0051); the memory and memo writers add their own existence checks
because ``insert_memory``/``insert_memo`` have no ON CONFLICT clause.

Composition-root-adjacent: called by ingest_findings.handler() once per
finding. Touches MemoryStore + the wiki PG schema + the wiki filesystem.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_layout import slugify
from mcp_server.handlers.ingest_findings_artifacts import FindingRecord
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import insert_memo, upsert_page
from mcp_server.infrastructure.pg_store_wiki_sources import upsert_page_sources
from mcp_server.infrastructure.wiki_store import write_page
from mcp_server.observability import silent_failure

_FINDING_LINK_KIND = "finding"
# Distinct from _FINDING_LINK_KIND ('finding' = code files the finding is
# ABOUT, from stage-4 matched_symbols). 'extracted_from' = the document
# the finding was EXTRACTED FROM (stage-1 ExtractedFinding.source_path,
# an absolute filesystem path to a source document, not project-relative
# code — see ingest_findings_artifacts.FindingRecord docstring). Kept as
# a separate link_kind, not folded into 'finding', so a graph reader can
# tell "provenance of the finding" apart from "subject matter of the
# finding" without inspecting confidence/source metadata.
_SOURCE_DOCUMENT_LINK_KIND = "extracted_from"
_MEMO_AUTHOR = "ap-pipeline"


def finding_tag(run_id: str, finding_id: str) -> str:
    """Canonical tag anchoring a memory/memo to one (run_id, finding_id)."""
    return f"ap-finding:{run_id}:{finding_id}"


def _memory_tags(mem: dict) -> list:
    raw = mem.get("tags", [])
    return raw if isinstance(raw, list) else []


def find_existing_memory(
    store: MemoryStore, run_id: str, finding_id: str
) -> int | None:
    """Return the memory id already written for this finding, or None."""
    tag = finding_tag(run_id, finding_id)
    try:
        mems = store.get_memories_by_tag(tag, limit=5)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("ingest_findings.find_existing", exc)
        return None
    for mem in mems:
        if tag in _memory_tags(mem):
            return mem.get("id")
    return None


def write_finding_memory(
    store: MemoryStore, finding: FindingRecord
) -> tuple[int, bool]:
    """Write (or reuse) the one memory representing this finding.

    Postcondition: returns (memory_id, created). ``created`` is False when
    an earlier ingestion of the same (run_id, finding_id) already wrote
    this memory — no duplicate row is inserted (idempotence).
    """
    existing = find_existing_memory(store, finding.run_id, finding.finding_id)
    if existing is not None:
        return existing, False

    tag = finding_tag(finding.run_id, finding.finding_id)
    if finding.verified:
        content = (
            f"AP finding verified (run {finding.run_id}, {finding.finding_id}): "
            f"{finding.title}. {finding.description}"
        ).strip()
        tags = ["finding", "verified", tag]
        importance, heat, confidence, protected = 0.7, 0.8, 0.9, True
    else:
        content = (
            f"AP finding hypothesis, unverified (run {finding.run_id}, "
            f"{finding.finding_id}): {finding.title}. {finding.description}"
        ).strip()
        tags = ["finding", "hypothesis", tag]
        importance, heat, confidence, protected = 0.3, 0.4, 0.3, False

    record = {
        "content": content,
        "tags": tags,
        "source": "ingest_findings",
        "domain": "ap-findings",
        "directory_context": f"run:{finding.run_id}",
        "importance": importance,
        "heat": heat,
        "confidence": confidence,
        "is_protected": protected,
        # M-D2 (7.4): bulk ingestion from the AP pipeline — bypasses the
        # `remember` gate entirely (direct insert_memory), same rationale
        # as ingest_codebase/seed_project.
        "write_class": "mechanical",
    }
    return store.insert_memory(record), True


def _slug(finding: FindingRecord) -> str:
    return slugify(f"{finding.run_id}-{finding.finding_id}")


def _page_rel_path(finding: FindingRecord) -> str:
    return f"reference/findings/{_slug(finding)}.md"


def _render_finding_page(finding: FindingRecord) -> str:
    lines = [
        "---",
        f"title: {finding.title}",
        "kind: finding",
        "tags: [finding, verified, ap-pipeline]",
        "source: ingest_findings",
        f"run_id: {finding.run_id}",
        f"finding_id: {finding.finding_id}",
        "---",
        "",
        f"# {finding.title}",
        "",
        finding.description or "_No description provided._",
        "",
        "## Provenance",
        "",
        f"- Run: `{finding.run_id}`",
        f"- Finding: `{finding.finding_id}`",
        f"- Refined artifact: `{finding.refined_rel_path}`",
    ]
    if finding.source_path:
        lines.append(f"- Extracted from: `{finding.source_path}`")
    if finding.file_paths:
        lines.append("")
        lines.append("## Files")
        lines.append("")
        lines.extend(f"- `{p}`" for p in finding.file_paths)
    return "\n".join(lines) + "\n"


def write_finding_page(conn: Any, finding: FindingRecord, memory_id: int) -> int:
    """Write the wiki page for a VERIFIED finding: filesystem + wiki.pages
    + wiki.page_sources(link_kind='finding') + wiki.page_sources
    (link_kind='extracted_from', when source_path is present). Returns
    the page_id.

    Precondition: finding.verified is True (caller gates this — D2:
    "a hypothesis is not documentation").
    Postcondition: wiki.pages has a row for this rel_path (idempotent via
    upsert_page's ON CONFLICT); wiki.page_sources has one row per
    finding.file_paths entry under link_kind='finding' (code files the
    finding is ABOUT) and, iff finding.source_path is not None, exactly
    one row under link_kind='extracted_from' (the document the finding
    was extracted FROM) — both idempotent via upsert_page_sources's
    DELETE+INSERT scoped to (page_id, link_kind). ``finding.file_paths``
    is empty unless the pipeline convention below was followed for this
    finding; ``source_path`` is orthogonal (set at stage-1, independent
    of whether stage-4 ever ran).

    Pipeline convention: stage-4 (``prepare_prd_input``) must be run for
    a verified finding BEFORE calling ``ingest_findings`` to obtain any
    code anchoring (link_kind='finding') — ``file_paths`` is empty, not
    guessed, when stage-4 never ran for this finding (see
    ``ingest_findings_artifacts._extract_file_paths``).
    """
    rel_path = _page_rel_path(finding)
    markdown = _render_finding_page(finding)
    write_page(WIKI_ROOT, rel_path, markdown, mode="replace")

    page_row = {
        "memory_id": memory_id,
        "rel_path": rel_path,
        "slug": _slug(finding),
        "kind": "finding",
        "title": finding.title,
        "domain": "ap-findings",
        "domains": ["ap-findings"],
        "tags": ["finding", "verified", "ap-pipeline"],
        "status": "seedling",
        "lifecycle_state": "active",
        "lead": (finding.description or "")[:280],
        "body": markdown,
    }
    page_id, _was_modified = upsert_page(conn, page_row)
    upsert_page_sources(
        conn,
        page_id,
        finding.file_paths,
        link_kind=_FINDING_LINK_KIND,
        source=_MEMO_AUTHOR,
        confidence=1.0,
    )
    if finding.source_path is not None:
        upsert_page_sources(
            conn,
            page_id,
            [finding.source_path],
            link_kind=_SOURCE_DOCUMENT_LINK_KIND,
            source=_MEMO_AUTHOR,
            confidence=1.0,
        )
    return page_id


def _memo_exists(conn: Any, run_id: str, finding_id: str, stage: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM wiki.memos WHERE author = %s "
            "AND inputs->>'run_id' = %s AND inputs->>'finding_id' = %s "
            "AND inputs->>'stage' = %s LIMIT 1",
            (_MEMO_AUTHOR, run_id, finding_id, stage),
        )
        return cur.fetchone() is not None


def write_receipt_memos(conn: Any, finding: FindingRecord, page_id: int) -> int:
    """Insert one wiki.memos row per receipt not already recorded.

    Postcondition: for every Receipt in finding.receipts, exactly one
    wiki.memos row exists with inputs matching (run_id, finding_id,
    stage) — re-running this on the same receipts inserts zero new rows
    (idempotence via the existence check, since wiki.memos has no unique
    constraint to ON CONFLICT against). ``inputs.transcript_digest`` is
    present (verbatim copy of AP's own field, not recomputed) iff the
    receipt is stage-2 AND AP's stage-2.verified.json actually carried a
    ``transcript_digest`` field — absent otherwise, never a placeholder.
    Returns the count of memos actually inserted this call.
    """
    inserted = 0
    for receipt in finding.receipts:
        if _memo_exists(conn, finding.run_id, finding.finding_id, receipt.stage):
            continue
        inputs: dict[str, Any] = {
            "run_id": finding.run_id,
            "finding_id": finding.finding_id,
            "stage": receipt.stage,
            "artifact_path": receipt.rel_path,
            "digest": receipt.digest,
            "digest_algorithm": "sha256",
        }
        if receipt.transcript_digest is not None:
            inputs["transcript_digest"] = receipt.transcript_digest
        insert_memo(
            conn,
            subject_type="page",
            subject_id=page_id,
            decision=receipt.verdict,
            rationale=(
                f"AP {receipt.stage} receipt for {finding.finding_id} "
                f"(run {finding.run_id})"
            ),
            inputs=inputs,
            confidence=1.0 if receipt.verdict in ("verified", "gates_passed") else 0.5,
            author=_MEMO_AUTHOR,
        )
        inserted += 1
    return inserted


def write_finding(
    store: MemoryStore, conn: Any, finding: FindingRecord
) -> dict[str, Any]:
    """Full write for one finding: memory, and (if verified) page + memos.

    This is the per-finding orchestration step; ingest_findings.handler()
    calls it once per finding_id in index.json.
    """
    memory_id, memory_created = write_finding_memory(store, finding)
    result: dict[str, Any] = {
        "finding_id": finding.finding_id,
        "verified": finding.verified,
        "memory_id": memory_id,
        "memory_created": memory_created,
        "page_id": None,
        "memos_written": 0,
    }
    if not finding.verified:
        return result

    page_id = write_finding_page(conn, finding, memory_id)
    result["page_id"] = page_id
    result["memos_written"] = write_receipt_memos(conn, finding, page_id)
    return result
