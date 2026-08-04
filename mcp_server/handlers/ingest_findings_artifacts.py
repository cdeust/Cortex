"""Pure parsing of ai-architect-mcp-codebase (AP) findings artifacts (INC5.1).

AP writes ONLY files under ``<output_dir>/runs/<run_id>/`` (ADR-0052 D1:
Cortex pulls, AP never pushes; no network/PG client exists in AP). This
module reads those files off disk and returns typed, JSON-agnostic
records. It never touches PostgreSQL, the wiki filesystem, or Cortex's
MemoryStore — that is ``ingest_findings_writers``'s job (SRP split,
coding-standards.md 1.1).

Artifact layout confirmed by reading AP's own source (not guessed):
  - ``index.json``                              main.rs:274-281 (Index)
  - ``findings/<id>/stage-1.refined.json``       main.rs:92, 243-249
  - ``findings/<id>/stage-2.verified.json``      main.rs:107, 1195-1213
  - ``findings/<id>/stage-4.prd_input.json``     prd_input.rs:38 (optional)
  - ``findings/<id>/stage-6.validation.json``    prd_validator.rs:27 (optional)
  - ``findings/<id>/stage-8.security.json``      security_gates.rs:35 (optional)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

INDEX_FILE_NAME = "index.json"
REFINED_FILE_NAME = "stage-1.refined.json"
VERIFIED_FILE_NAME = "stage-2.verified.json"
PRD_INPUT_FILE_NAME = "stage-4.prd_input.json"
VALIDATION_FILE_NAME = "stage-6.validation.json"
SECURITY_FILE_NAME = "stage-8.security.json"

# (stage label, filename, verdict-extraction key) — receipts checked in
# this fixed order for every finding. stage-2 is present iff verified.
_RECEIPT_SPECS: tuple[tuple[str, str], ...] = (
    ("stage-2", VERIFIED_FILE_NAME),
    ("stage-6", VALIDATION_FILE_NAME),
    ("stage-8", SECURITY_FILE_NAME),
)


class MalformedArtifactError(Exception):
    """Raised when a required artifact file exists but does not parse."""


@dataclass(frozen=True)
class Receipt:
    """One stage receipt (stage-2/6/8), digest-anchored to its file on disk.

    ``digest`` is sha256 over the RAW BYTES of the artifact file as read
    from disk — re-verifiable by any caller via ``hashlib.sha256(open(
    artifact_path, 'rb').read())``, independent of AP's internal
    canonicalization.

    ``transcript_digest`` (stage-2 only, else None) is a VERBATIM COPY of
    the ``transcript_digest`` field AP itself writes into
    ``stage-2.verified.json`` (main.rs ``VerifiedArtifact.transcript_digest``,
    serialized main.rs:1738) — AP's own semantic digest over the
    canonicalized transcript, which survives a re-serialization of the
    artifact file (whitespace/key-order changes) that would change
    ``digest`` above. This is a copy of AP's claim, never a
    re-derivation: reimplementing AP's canonicalization algorithm in
    Python would be a second, driftable implementation of the same
    procedure (INC5.1's original digest decision, preserved). The two
    digests are deliberately independent anchors: ``digest`` = raw bytes
    (strict, catches ANY byte change), ``transcript_digest`` = AP's
    semantic claim (survives harmless re-serialization, distrust-then-
    verify against AP's own computation).
    """

    stage: str
    rel_path: str
    digest: str
    verdict: str
    raw: dict[str, Any]
    transcript_digest: str | None = None


@dataclass(frozen=True)
class FindingRecord:
    """One finding's ingestible state, gradated by its stage-2 verdict.

    ``source_path`` (from stage-1's ``ExtractedFinding.source_path``,
    main.rs:201 — an ``Option<String>``, an ABSOLUTE filesystem path to
    the document AP extracted this finding FROM, or None when the
    finding was submitted inline) is semantically DISTINCT from
    ``file_paths`` (stage-4's ``matched_symbols`` — project-relative code
    files the finding is ABOUT). ``source_path`` is extraction
    provenance ("where this finding came from"); ``file_paths`` is
    subject matter ("what code this finding concerns"). See
    ``ingest_findings_writers._SOURCE_DOCUMENT_LINK_KIND`` for how the
    two are kept distinguishable in ``wiki.page_sources``.
    """

    run_id: str
    finding_id: str
    verified: bool
    title: str
    description: str
    refined_rel_path: str
    file_paths: list[str] = field(default_factory=list)
    receipts: list[Receipt] = field(default_factory=list)
    source_path: str | None = None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    """Read + parse one JSON artifact; returns (parsed, sha256_of_raw_bytes).

    Raises MalformedArtifactError on I/O failure or invalid JSON.
    """
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise MalformedArtifactError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(raw_bytes), _sha256_bytes(raw_bytes)
    except ValueError as exc:
        raise MalformedArtifactError(f"invalid JSON in {path}: {exc}") from exc


def read_index(output_dir: Path, run_id: str) -> dict[str, Any]:
    """Read ``runs/<run_id>/index.json``.

    Raises MalformedArtifactError if absent/bad.
    """
    index_path = output_dir / "runs" / run_id / INDEX_FILE_NAME
    if not index_path.exists():
        raise MalformedArtifactError(f"no index.json at {index_path}")
    data, _ = _read_json(index_path)
    if "findings" not in data:
        raise MalformedArtifactError(f"index.json at {index_path} has no 'findings'")
    return data


def _finding_dir(output_dir: Path, run_id: str, finding_id: str) -> Path:
    return output_dir / "runs" / run_id / "findings" / finding_id


def _load_receipt(finding_dir: Path, stage: str, file_name: str) -> Receipt | None:
    """Load one optional receipt file; None when the stage never ran.

    ``transcript_digest`` is populated only for stage-2 (the only receipt
    kind that carries this field per ``VerifiedArtifact``, main.rs:1199-
    1213) and only when AP's own JSON actually has it — a value is never
    invented when absent (coding-standards.md §8, "no invented claims").
    """
    path = finding_dir / file_name
    if not path.exists():
        return None
    raw, digest = _read_json(path)
    verdict = _extract_verdict(stage, raw)
    transcript_digest = None
    if stage == "stage-2":
        candidate = raw.get("transcript_digest")
        transcript_digest = (
            candidate if isinstance(candidate, str) and candidate else None
        )
    return Receipt(
        stage=stage,
        rel_path=file_name,
        digest=digest,
        verdict=verdict,
        raw=raw,
        transcript_digest=transcript_digest,
    )


def _extract_verdict(stage: str, raw: dict[str, Any]) -> str:
    """Pull the one-word verdict AP itself computed for this receipt kind."""
    if stage == "stage-2":
        return "verified" if raw.get("verified") else "not_verified"
    if stage == "stage-6":
        return str(raw.get("validation_status", "unknown"))
    if stage == "stage-8":
        return "gates_passed" if raw.get("gates_passed") else "gates_failed"
    return "unknown"


def _extract_file_paths(finding_dir: Path) -> list[str]:
    """File paths a finding touches, from stage-4's matched symbols (D4).

    stage-4.prd_input.json is optional (only present when
    ``prepare_prd_input`` ran for this finding). When absent, returns an
    empty list rather than guessing paths out of free-text description —
    inventing paths via regex would be an unsourced heuristic (coding-
    standards.md 8, "no invented constants/claims"); "no stage-4 data"
    means "I don't know the affected files", not "0 files".
    ``matched_symbols[].qualified_name`` is ``"<file_path>::<symbol>"``
    (AP's own convention, confirmed in prd_input.rs report_to_json).
    """
    path = finding_dir / PRD_INPUT_FILE_NAME
    if not path.exists():
        return []
    try:
        raw, _ = _read_json(path)
    except MalformedArtifactError:
        return []
    matched = (
        raw.get("report", {}).get("matched_symbols") or raw.get("matched_symbols") or []
    )
    seen: list[str] = []
    for m in matched:
        qn = m.get("qualified_name") if isinstance(m, dict) else None
        if not qn or "::" not in qn:
            continue
        file_part = qn.split("::", 1)[0]
        if file_part and file_part not in seen:
            seen.append(file_part)
    return seen


def load_finding(output_dir: Path, run_id: str, finding_id: str) -> FindingRecord:
    """Assemble a FindingRecord from every artifact present for one finding.

    Precondition:  ``stage-1.refined.json`` exists for this finding
                    (index.json only lists findings that reached stage 1b).
    Postcondition: verified findings carry a stage-2 Receipt in
                    ``receipts[0]``; non-verified findings carry none.
    """
    finding_dir = _finding_dir(output_dir, run_id, finding_id)
    refined_path = finding_dir / REFINED_FILE_NAME
    if not refined_path.exists():
        raise MalformedArtifactError(f"no {REFINED_FILE_NAME} at {finding_dir}")
    refined, _ = _read_json(refined_path)
    extracted = refined.get("extracted", {})
    raw_source_path = extracted.get("source_path")
    source_path = (
        raw_source_path
        if isinstance(raw_source_path, str) and raw_source_path
        else None
    )

    receipts: list[Receipt] = []
    for stage, file_name in _RECEIPT_SPECS:
        r = _load_receipt(finding_dir, stage, file_name)
        if r is not None:
            receipts.append(r)

    verified = any(r.stage == "stage-2" and r.verdict == "verified" for r in receipts)

    return FindingRecord(
        run_id=run_id,
        finding_id=finding_id,
        verified=verified,
        title=extracted.get("title", finding_id),
        description=extracted.get("description") or "",
        refined_rel_path=f"findings/{finding_id}/{REFINED_FILE_NAME}",
        file_paths=_extract_file_paths(finding_dir),
        receipts=receipts,
        source_path=source_path,
    )
