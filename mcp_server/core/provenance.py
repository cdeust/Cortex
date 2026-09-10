"""Provenance grading — pure business logic (I6-D6).

source: ADR-0231"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Grade vocabulary ────────────────────────────────────────────────────────
VERIFIED = "verified"
VERIFIABLE = "verifiable"
UNVERIFIABLE = "unverifiable"

GRADES = (VERIFIED, VERIFIABLE, UNVERIFIABLE)
_RANK = {UNVERIFIABLE: 0, VERIFIABLE: 1, VERIFIED: 2}  # worst → best

# ── Reference extraction ────────────────────────────────────────────────────

# Hex tokens that plausibly look like a git commit SHA (short or full).
# All-digit runs are excluded (those are more likely counters/timestamps).
_COMMIT_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

_URL_RE = re.compile(r"https?://\S+")

# Content-addressed artifact pointer: <...>/artifacts/<yyyy-mm>/<16-hex>.md
# (infrastructure/artifact_store.py: ARTIFACTS_DIR / <yyyy-mm> / sha256[:16].md)
_ARTIFACT_RE = re.compile(
    r"([\w./\\-]*artifacts[/\\]\d{4}-\d{2}[/\\]([0-9a-f]{16})\.md)"
)

# source: ADR-0231
_CITATION_RE = re.compile(
    r"\b(?:10\.\d{4,9}/\S+|arXiv:\d{4}\.\d{4,5})\b", re.IGNORECASE
)


def extract_commit_refs(content: str) -> list[str]:
    """Deduplicated candidate commit SHAs (hex, 7-40 chars, not all-digit)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _COMMIT_RE.finditer(content or ""):
        tok = m.group(0)
        if tok.isdigit() or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def extract_url_refs(content: str) -> list[str]:
    """Deduplicated http(s) URLs, trailing punctuation stripped."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL_RE.finditer(content or ""):
        url = m.group(0).rstrip(").,;:'\"")
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def extract_artifact_refs(content: str) -> list[tuple[str, str]]:
    """Deduplicated (artifact_path, embedded_sha256_prefix) pairs."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for m in _ARTIFACT_RE.finditer(content or ""):
        path, digest = m.group(1), m.group(2)
        if path not in seen:
            seen.add(path)
            out.append((path, digest))
    return out


def has_citation_ref(content: str) -> bool:
    """True iff content carries a structured DOI/arXiv citation marker.

    source: ADR-0231
    """
    return bool(_CITATION_RE.search(content or ""))


# ── Grading ──────────────────────────────────────────────────────────────────


@dataclass
class ProvenanceReport:
    """Result of a provenance-grading pass for a single memory."""

    memory_id: int
    grade: str
    ref_counts: dict[str, int]
    dead_refs: list[str] = field(default_factory=list)
    uncheckable_refs: list[str] = field(default_factory=list)
    reason: str = "no_extractable_reference"


def _build_reason(grade: str, dead: list[str], uncheckable: list[str]) -> str:
    if grade == UNVERIFIABLE and dead:
        return f"dead_refs: {', '.join(dead[:3])}"
    if grade == UNVERIFIABLE:
        return "no_extractable_reference"
    if grade == VERIFIABLE and uncheckable:
        return f"uncheckable_refs: {', '.join(uncheckable[:3])}"
    return "all_refs_verified"


def grade_provenance(
    memory_id: int,
    *,
    file_refs: list[str],
    existing_paths: set[str],
    commit_refs: list[str],
    commit_verdicts: dict[str, bool],
    url_refs: list[str],
    url_verdicts: dict[str, bool | None],
    artifact_refs: list[tuple[str, str]],
    artifact_verdicts: dict[str, bool],
    has_citation: bool,
) -> ProvenanceReport:
    """Grade one memory from pre-resolved per-reference outcomes.

    precondition: every ref in file_refs/commit_refs/url_refs/(path for
    artifact_refs) has, at most, a corresponding entry in its verdicts dict
    (a missing entry is treated as the least-favorable outcome for that
    type, never crashes).
    postcondition: returns a ProvenanceReport whose grade is the worst
    outcome (UNVERIFIABLE < VERIFIABLE < VERIFIED) among all reference
    outcomes, or UNVERIFIABLE when there is no extractable reference at all.
    """
    outcomes: list[str] = []
    dead: list[str] = []
    uncheckable: list[str] = []

    for p in file_refs:
        if p in existing_paths:
            outcomes.append(VERIFIED)
        else:
            outcomes.append(UNVERIFIABLE)
            dead.append(p)

    for sha in commit_refs:
        if commit_verdicts.get(sha, False):
            outcomes.append(VERIFIED)
        else:
            outcomes.append(VERIFIABLE)
            uncheckable.append(sha)

    for url in url_refs:
        verdict = url_verdicts.get(url)
        if verdict is False:
            outcomes.append(UNVERIFIABLE)
            dead.append(url)
        else:
            outcomes.append(VERIFIABLE)
            if verdict is None:
                uncheckable.append(url)

    for path, _digest in artifact_refs:
        if artifact_verdicts.get(path, False):
            outcomes.append(VERIFIED)
        else:
            outcomes.append(UNVERIFIABLE)
            dead.append(path)

    if has_citation:
        outcomes.append(VERIFIABLE)

    if not outcomes:
        return ProvenanceReport(
            memory_id=memory_id,
            grade=UNVERIFIABLE,
            ref_counts=_ref_counts(
                file_refs, commit_refs, url_refs, artifact_refs, has_citation
            ),
            # dead_refs/uncheckable_refs are left to the dataclass defaults:
            # restating the empty lists here duplicates the default in two
            # places and produces only equivalent mutants (issue #389).
            reason="no_extractable_reference",
        )

    grade = min(outcomes, key=lambda g: _RANK[g])
    return ProvenanceReport(
        memory_id=memory_id,
        grade=grade,
        ref_counts=_ref_counts(
            file_refs, commit_refs, url_refs, artifact_refs, has_citation
        ),
        dead_refs=dead,
        uncheckable_refs=uncheckable,
        reason=_build_reason(grade, dead, uncheckable),
    )


def _ref_counts(
    file_refs: list[str],
    commit_refs: list[str],
    url_refs: list[str],
    artifact_refs: list[tuple[str, str]],
    has_citation: bool,
) -> dict[str, int]:
    return {
        "file": len(file_refs),
        "commit": len(commit_refs),
        "url": len(url_refs),
        "artifact": len(artifact_refs),
        "citation": 1 if has_citation else 0,
    }


# source: ADR-0231


_WRITE_TIME_HINTS: dict[str, str] = {
    VERIFIED: "All checkable references verified locally.",
    VERIFIABLE: (
        "References present but not conclusively checked at write time "
        "(e.g. a commit whose repo isn't locally available, or a "
        "citation -- DOI/arXiv are never auto-verified)."
    ),
    UNVERIFIABLE: (
        "No checkable reference found (file path, commit SHA, URL, or "
        "content-addressed artifact digest)."
    ),
}

# source: ADR-0231


_DELIBERATE_UNVERIFIABLE_SUFFIX = (
    " For a durable claim, add one -- testimony without a reference "
    "degrades under recall competition and stays 'unverifiable' through "
    "the next validate_memory pass."
)


def _named_dead_refs(dead_refs: list[str]) -> str:
    """Up to 3 dead refs, comma-joined, with a "(+N more)" tail."""
    named = ", ".join(dead_refs[:3])
    remaining = len(dead_refs) - 3
    return f"{named} (+{remaining} more)" if remaining > 0 else named


def _dead_ref_hint_root_missing(report: ProvenanceReport, root: str) -> str:
    """State 2a: the resolution root itself is not a directory on disk.

    source: ADR-0231
    """
    return (
        f"{len(report.dead_refs)} checkable reference(s) could not be "
        f"resolved because the resolution root '{root}' is not a directory "
        f"on disk: {_named_dead_refs(report.dead_refs)}. Pass a valid "
        "`directory`, then supersede this memory."
    )


def _dead_ref_hint_root_implicit(report: ProvenanceReport, root: str) -> str:
    """State 2b: no `directory` argument was given.

    source: ADR-0231
    """
    total = sum(report.ref_counts.values())
    return (
        f"{len(report.dead_refs)} of {total} checkable reference(s) could "
        f"not be resolved against '{root}' -- no `directory` was passed to "
        "this write, so resolution defaulted to the process's current "
        f"working directory: {_named_dead_refs(report.dead_refs)}. Pass "
        "`directory` explicitly (your project root) and retry, or drop "
        "the reference if it is genuinely gone."
    )


def _dead_ref_hint_root_explicit(report: ProvenanceReport, root: str) -> str:
    """State 3: resolved against a real, explicitly-given root, and the reference(s)
    are genuinely absent there.

    source: ADR-0231
    """
    total = sum(report.ref_counts.values())
    return (
        f"{len(report.dead_refs)} of {total} checkable reference(s) could "
        f"not be resolved against '{root}': {_named_dead_refs(report.dead_refs)}. "
        "Fix the path/URL or drop it, then supersede this memory."
    )


def _unverifiable_hint(
    report: ProvenanceReport,
    *,
    resolution_root: str,
    resolution_root_explicit: bool,
    resolution_root_exists: bool,
) -> str:
    """UNVERIFIABLE-branch hint.

    source: ADR-0231

    precondition: ``report.grade == UNVERIFIABLE``; ``resolution_root`` is
        the directory refs were resolved against (may be "");
        ``resolution_root_explicit`` is whether the caller passed
        ``directory`` (False = implicit ``os.getcwd()`` fallback);
        ``resolution_root_exists`` is whether that root is a real directory
        on disk (always True when ``resolution_root_explicit`` is False,
        since ``os.getcwd()`` cannot fail to exist for a running process).
    postcondition: when ``report.dead_refs`` is empty, returns the
        unchanged "no reference at all" wording (state 1). Otherwise names
        up to 3 dead refs AND the resolution root used, picking exactly one
        of three mutually exclusive branches: root missing on disk (state
        2a), root implicit/unstated (state 2b), or root explicit and real
        (state 3, genuinely dead).
    """
    if not report.dead_refs:
        return _WRITE_TIME_HINTS[UNVERIFIABLE]
    root = resolution_root or "(unresolved)"
    if not resolution_root_exists:
        return _dead_ref_hint_root_missing(report, root)
    if not resolution_root_explicit:
        return _dead_ref_hint_root_implicit(report, root)
    return _dead_ref_hint_root_explicit(report, root)


def write_time_hint(
    report: ProvenanceReport,
    write_class: str = "",
    *,
    resolution_root: str = "",
    resolution_root_explicit: bool = True,
    resolution_root_exists: bool = True,
) -> str:
    """Deterministic, templated feedback for the write-time caller (M-D5).

    precondition: report comes from grade_from_content or grade_provenance;
        write_class is the resolved class or an empty string. The resolution
        root flags describe the caller's reference-resolution directory.
    postcondition: returns a non-persisted hint keyed by report.grade.
        VERIFIED/VERIFIABLE use a lookup. UNVERIFIABLE includes dead refs
        and resolution root details, with an additional deliberate-write hint.
    source: ADR-0231"""
    if report.grade == UNVERIFIABLE:
        hint = _unverifiable_hint(
            report,
            resolution_root=resolution_root,
            resolution_root_explicit=resolution_root_explicit,
            resolution_root_exists=resolution_root_exists,
        )
    else:
        hint = _WRITE_TIME_HINTS[report.grade]
    if report.grade == UNVERIFIABLE and write_class == "deliberate":
        hint += _DELIBERATE_UNVERIFIABLE_SUFFIX
    return hint
