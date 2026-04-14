"""Phase 4 — Staleness brake for wiki pages.

A page becomes stale when the file references it cites no longer
exist on disk. Stale pages get is_stale=True and lose heat faster
(half-life multiplier).

Pure logic: this module is given a page's referenced file paths and
a per-path existence map (computed by the handler with filesystem
I/O), and returns the decision.

Staleness signal sources:
  - claim_events.evidence_refs where kind='file' (most reliable)
  - Inline file-pattern matches in lead/sections (best-effort)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FILE_REF_RE = re.compile(
    r"\b([\w./-]+\.(?:py|js|ts|md|json|yaml|yml|sql|go|rs|rb|java|cpp|c|h|hpp|sh|toml))\b"
)

# A page is stale when this fraction of its file refs are missing.
STALE_THRESHOLD = 0.5
# A page must reference at least this many files for staleness to apply
# (avoid false positives from pages with one stray file mention).
MIN_FILE_REFS = 2


@dataclass(frozen=True)
class StalenessDecision:
    """Per-page staleness verdict."""

    page_id: int
    file_refs: list[str]
    missing_refs: list[str]
    is_stale_now: bool
    is_stale_was: bool
    transitioned: bool
    rationale: str


def extract_file_refs(text: str) -> list[str]:
    """Return distinct file paths mentioned in a body of text."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _FILE_REF_RE.finditer(text):
        ref = m.group(1)
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def evaluate_staleness(
    *,
    page_id: int,
    is_stale_was: bool,
    file_refs: list[str],
    existence: dict[str, bool],
) -> StalenessDecision:
    """Decide whether a page is stale.

    Inputs:
      page_id       — wiki.pages.id
      is_stale_was  — current value on the page row
      file_refs     — list of file paths mentioned by the page (claim
                      evidence + inline pattern matches; deduped)
      existence     — {path: True if exists, False if missing}

    A page is stale iff:
      - len(file_refs) >= MIN_FILE_REFS
      - missing / total >= STALE_THRESHOLD
    """
    if len(file_refs) < MIN_FILE_REFS:
        return StalenessDecision(
            page_id=page_id,
            file_refs=file_refs,
            missing_refs=[],
            is_stale_now=False,
            is_stale_was=is_stale_was,
            transitioned=is_stale_was,  # True if we're un-staling
            rationale=(f"too few file refs ({len(file_refs)} < {MIN_FILE_REFS})"),
        )

    missing = [ref for ref in file_refs if not existence.get(ref, False)]
    fraction = len(missing) / len(file_refs)
    is_stale_now = fraction >= STALE_THRESHOLD
    return StalenessDecision(
        page_id=page_id,
        file_refs=file_refs,
        missing_refs=missing,
        is_stale_now=is_stale_now,
        is_stale_was=is_stale_was,
        transitioned=is_stale_now != is_stale_was,
        rationale=(
            f"{len(missing)}/{len(file_refs)} refs missing "
            f"({fraction * 100:.0f}% — threshold {int(STALE_THRESHOLD * 100)}%)"
        ),
    )


def harvest_page_refs(page: dict, claim_evidence_files: list[str]) -> list[str]:
    """Collect all file refs a page should be checked against.

    Combines:
      - claim-derived file refs (high signal, from extractor)
      - inline file patterns in lead + section bodies (best effort)
    """
    refs: set[str] = set(claim_evidence_files or [])
    refs.update(extract_file_refs(page.get("lead") or ""))
    sections = page.get("sections") or {}
    if isinstance(sections, dict):
        for body in sections.values():
            refs.update(extract_file_refs(str(body)))
    elif isinstance(sections, list):
        for s in sections:
            body = s.get("body") if isinstance(s, dict) else getattr(s, "body", "")
            refs.update(extract_file_refs(str(body)))
    return sorted(refs)


__all__ = [
    "STALE_THRESHOLD",
    "MIN_FILE_REFS",
    "StalenessDecision",
    "extract_file_refs",
    "evaluate_staleness",
    "harvest_page_refs",
]
