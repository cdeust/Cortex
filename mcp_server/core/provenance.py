"""Provenance grading — pure business logic (I6-D6).

Grades a memory's content by the CONTROLLABILITY of the external references
it makes: file paths, git commit SHAs, URLs, and content-addressed artifact
digests (``infrastructure/artifact_store.py``, ``sha256[:16]``). Citation
references (DOI / arXiv id) are recognized but never auto-checked — no
source exists to verify them against (coding-standards.md §8: "no source,
no implementation" applies equally to verification code).

Grade vocabulary (persisted to ``memories.source_attribution`` by
``handlers/validate_memory.py``, the sole writer of this grade going
forward — I6-D6):

  VERIFIED     — every controllable reference in the memory currently
                 checks out (all file paths exist, all commit SHAs resolve
                 in their memory's local repo, all artifact digests match).
  VERIFIABLE   — the memory carries references, but at least one could not
                 be conclusively checked here and now (repo unavailable
                 locally, URL not sampled this pass, a citation with no
                 automated check), and no CHECKED reference came back dead.
  UNVERIFIABLE — no reference at all (testimony only), OR at least one
                 checked reference is dead (missing file, unreachable URL,
                 missing/mismatched artifact digest).

Per-type grade ceiling (from the I6-D6 design table — not every reference
type can reach every grade):
  file path        → VERIFIED (exists) | UNVERIFIABLE (missing)
  git commit SHA    → VERIFIED (found in a locally-available repo) |
                       VERIFIABLE (repo unavailable locally, or the check
                       was inconclusive — a stale/shallow local clone is
                       indistinguishable from a genuinely dead SHA, so we
                       never penalize the memory to UNVERIFIABLE from a
                       commit ref alone)
  URL               → VERIFIABLE (2xx/3xx, or not sampled this pass) |
                       UNVERIFIABLE (4xx/5xx/timeout) — a URL can never
                       raise a memory to VERIFIED; the web fluctuates and
                       a dead link does not invalidate a historical fact
                       (kept OUT of the staleness score for the same
                       reason — see core/staleness.py).
  artifact digest   → VERIFIED (recomputed sha256[:16] matches) |
                       UNVERIFIABLE (artifact missing or hash mismatch)
  citation (DOI/arXiv) → VERIFIABLE at best — never auto-verified, never
                       marked dead.

The memory's overall grade is the WORST outcome among its references
(min over the ranking UNVERIFIABLE < VERIFIABLE < VERIFIED). A memory with
zero extractable references is UNVERIFIABLE (testimony only).

No I/O performed here. Callers (validate_memory) resolve existence /
reachability / repo availability and pass the outcomes in — the same
caller-resolves-I/O separation as core/staleness.py.
"""

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

# Citation markers this tool recognizes but never auto-checks: DOI and arXiv ids.
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
    """True iff content carries a structured DOI/arXiv citation marker."""
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
            dead_refs=[],
            uncheckable_refs=[],
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


# ── Write-time feedback (M-D5, 7.5) ─────────────────────────────────────────
#
# NOT a grade write path: this is a lookup table over the existing grade
# vocabulary (no new inference), used to hand the WRITER of a memory an
# immediate, human-readable nudge in the `remember()` response. Never
# persisted — `handlers/validate_memory.py` remains the sole writer of the
# grade vocabulary to `memories.source_attribution` (I6-D6); see that
# module's docstring and `handlers/remember_helpers.py::insert_and_post_process`
# for why a second writer to that column would silently defeat the C1
# confabulation gate (`core/source_monitoring.py::recall_confabulation_risk`).

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

# M-D2 (7.4) named the 'deliberate' write class as the one meant to carry
# durable, considered testimony -- an unverifiable deliberate write gets a
# stronger call-to-action than an unverifiable auto/derived/mechanical one
# (those are machine-authored by construction; asking them for a citation
# is meaningless).
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
    """State 2a (issue #345): the resolution root itself is not a directory
    on disk, so every file ref under it was necessarily unresolvable --
    the dead-refs list says nothing about whether the PATHS are wrong."""
    return (
        f"{len(report.dead_refs)} checkable reference(s) could not be "
        f"resolved because the resolution root '{root}' is not a directory "
        f"on disk: {_named_dead_refs(report.dead_refs)}. Pass a valid "
        "`directory`, then supersede this memory."
    )


def _dead_ref_hint_root_implicit(report: ProvenanceReport, root: str) -> str:
    """State 2b (issue #345): no `directory` argument was given, so
    resolution silently fell back to the server process's current working
    directory, which need not be the writer's project root."""
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
    """State 3 (issue #345): resolved against a real, explicitly-given
    root, and the reference(s) are genuinely absent there."""
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
    """UNVERIFIABLE-branch hint (issue #345).

    ``grade_provenance`` folds three distinct UNVERIFIABLE causes into one
    grade -- ``report.dead_refs`` (from ``_build_reason`` above) already
    separates "no reference at all" from "reference(s) resolved dead", but
    a caller reproduction (memory 4341427, 2026-08-08) showed a second dead
    -ref cause the naive fix still mislabels: refs that are perfectly real
    but were checked against the WRONG resolution root because the caller
    never passed ``directory`` (``grade_from_content``'s ``base_dir =
    directory or os.getcwd()`` fallback, ``handlers/remember_helpers.py``).
    Both a genuinely-dead ref and a wrong-root ref land in ``dead_refs``
    identically from ``grade_provenance``'s point of view (it only sees
    pre-resolved existence booleans) -- the distinction is caller-side
    context (was ``directory`` explicit? does the resolved root even exist
    on disk?), passed in here as booleans rather than re-derived with I/O
    (core/ stays zero-I/O; see module docstring).

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

    precondition: ``report`` came from ``grade_from_content``
        (``handlers/validate_memory.py``, write-path) or ``grade_provenance``
        generally; ``write_class`` is the resolved write class of the
        memory being written (M-D2, 7.4), or "" when not applicable.
        ``resolution_root``/``resolution_root_explicit``/
        ``resolution_root_exists`` (issue #345) describe the directory the
        caller resolved file refs against -- default to the pre-#345
        behaviour (explicit, existing, unnamed) so a caller that has not
        been updated to pass them gets the old wording unchanged.
    postcondition: returns a hint string keyed by ``report.grade``. For
        VERIFIED/VERIFIABLE this is a pure lookup (no new inference). For
        UNVERIFIABLE it further branches on ``report.dead_refs`` and the
        resolution-root booleans (issue #345) so a write whose references
        were extracted but resolved dead is told WHICH ones and AGAINST
        WHAT ROOT, instead of being told none was found -- a stronger
        call-to-action is appended when ``write_class == "deliberate"``.
        Never persisted; callers surface this in the write response only.
    """
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
