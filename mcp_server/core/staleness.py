"""Memory staleness detection — pure business logic.

Determines whether a stored memory is stale by examining the file references
it contains. Caller is responsible for resolving paths and checking existence;
this module only provides the logic to extract refs and score staleness.

A memory is considered stale when:
  - It references files that no longer exist (hard stale)
  - It references files whose content has drifted significantly (soft stale)
  - Its content describes a state that contradicts current filesystem state

No I/O performed here. Callers pass pre-resolved existence/change data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── File reference extraction ─────────────────────────────────────────────

# Matches Unix-style relative and absolute paths with a file extension
_PATH_RE = re.compile(
    r"(?:^|[\s\"'`(,])("
    r"(?:\.{0,2}/)?"  # optional leading ./ or ../
    r"(?:[\w@.-]+/)+"  # one or more path segments
    r"[\w@.-]+\.\w{1,10}"  # filename.ext
    r")(?:[\s\"'`:),]|$)",
    re.MULTILINE,
)

# Matches imports/requires that imply a local path
_IMPORT_PATH_RE = re.compile(
    r"""(?:import|from|require)\s+['"]([./][^'"]+)['"]""",
    re.MULTILINE,
)

# Common non-filesystem path patterns to exclude
_EXCLUDE_RE = re.compile(
    r"^https?://|^ftp://|^mailto:|localhost|\.(com|org|net|io|dev)$",
    re.IGNORECASE,
)


def extract_file_references(content: str) -> list[str]:
    """Extract file path references from memory content.

    Returns deduplicated list of candidate file paths mentioned in content.
    Filters out URLs, hostnames, and other non-filesystem strings.

    Args:
        content: Raw memory content string.
    """
    refs: set[str] = set()

    for m in _PATH_RE.finditer(content):
        path = m.group(1).strip()
        if path and not _EXCLUDE_RE.search(path) and len(path) < 256:
            refs.add(path)

    for m in _IMPORT_PATH_RE.finditer(content):
        path = m.group(1).strip()
        if path and len(path) < 256:
            refs.add(path)

    return sorted(refs)


# ── Staleness assessment ──────────────────────────────────────────────────


@dataclass
class StalenessReport:
    """Result of a staleness assessment for a single memory."""

    memory_id: int
    total_refs: int
    missing_refs: list[str]
    changed_refs: list[str]
    staleness_score: float  # 0.0 = fresh, 1.0 = fully stale
    is_stale: bool  # True if score >= threshold
    reason: str


def compute_staleness_score(
    total_refs: int,
    missing_count: int,
    changed_count: int,
    *,
    missing_weight: float = 1.0,
    changed_weight: float = 0.5,
) -> float:
    """Compute a 0–1 staleness score from reference outcomes.

    Missing files weight more than changed ones (a missing file is
    definitive evidence of staleness; a changed file is softer).

    Args:
        total_refs: Total file references found in the memory.
        missing_count: How many referenced files no longer exist.
        changed_count: How many referenced files exist but have changed.
        missing_weight: Score contribution per missing file (default 1.0 per ref).
        changed_weight: Score contribution per changed file (default 0.5 per ref).
    """
    if total_refs == 0:
        return 0.0
    raw = (missing_count * missing_weight + changed_count * changed_weight) / total_refs
    return min(1.0, raw)


def _build_staleness_reason(
    missing: list[str],
    changed: list[str],
) -> str:
    """Build a human-readable staleness reason string."""
    if missing:
        return f"missing_files: {', '.join(missing[:3])}"
    if changed:
        return f"changed_files: {', '.join(changed[:3])}"
    return "all_refs_valid"


def assess_staleness(
    memory_id: int,
    content: str,
    *,
    existing_paths: set[str] | None = None,
    changed_paths: set[str] | None = None,
    threshold: float = 0.5,
) -> StalenessReport:
    """Assess staleness of a memory given pre-resolved path existence data."""
    refs = extract_file_references(content)

    if not refs or existing_paths is None:
        return StalenessReport(
            memory_id=memory_id,
            total_refs=len(refs),
            missing_refs=[],
            changed_refs=[],
            staleness_score=0.0,
            is_stale=False,
            reason="no_refs" if not refs else "no_existence_data",
        )

    missing = [r for r in refs if r not in existing_paths]
    changed = [
        r for r in refs if r in existing_paths and changed_paths and r in changed_paths
    ]
    score = compute_staleness_score(len(refs), len(missing), len(changed))

    return StalenessReport(
        memory_id=memory_id,
        total_refs=len(refs),
        missing_refs=missing,
        changed_refs=changed,
        staleness_score=round(score, 4),
        is_stale=score >= threshold,
        reason=_build_staleness_reason(missing, changed),
    )


# ── Batch helpers ─────────────────────────────────────────────────────────


def collect_all_refs(memories: list[dict]) -> list[str]:
    """Collect all unique file paths referenced across a list of memories.

    Used by the validate_memory handler to batch-resolve paths in one pass
    before calling assess_staleness per memory.

    Args:
        memories: List of memory dicts with at least a 'content' key.
    """
    all_refs: set[str] = set()
    for mem in memories:
        for ref in extract_file_references(mem.get("content", "")):
            all_refs.add(ref)
    return sorted(all_refs)
