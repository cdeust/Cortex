"""Handler: validate_memory — graded provenance verifier (I6-D6).

Two distinct outputs per memory, both computed from the same reference
extraction pass:

1. Staleness (unchanged from before I6-D6): FILE PATHS ONLY feed the
   staleness score (core/staleness.py). URLs, commits, artifact digests,
   and citations are never extraction inputs to ``is_stale`` — a memory
   describing a historical fact is not stale just because a URL it
   mentions went 404 (see core/staleness.py header). This tool is
   BIDIRECTIONAL on staleness since I6-D6: a stale memory whose file
   refs all resolve again is rehabilitated (``is_stale`` set back to
   false), not just flagged one-directionally.
2. Provenance grade (new, I6-D6): every reference type — file paths, git
   commit SHAs, URLs (HEAD-checked, bounded sample), and content-addressed
   artifact digests (sha256[:16] recomputation) — is checked and combined
   into one of verified / verifiable / unverifiable (core/provenance.py),
   persisted to ``memories.source_attribution``. This handler is the sole
   writer of that grade going forward; a prior write from a different
   subsystem (C1 source/reality monitoring, remember_helpers.py) is a
   distinct, non-grade epistemic-origin classification that this handler's
   grade overwrites on the memory's next verification pass. Citations
   (DOI/arXiv) are recognized but never auto-verified — no source exists
   to check them against (coding-standards.md §8).

Can target a single memory, a domain, a directory, or all memories
(cursor-paginated via ``after_id``, 1000 per call).
"""

from __future__ import annotations

import hashlib
import http.client
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp_server.core import provenance
from mcp_server.core.staleness import assess_staleness, collect_all_refs
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.shared.subprocess_safe import run_with_hard_timeout

# ── Bounds (I6-D6: no unbounded network fan-out from a memory-maintenance
# tool) ───────────────────────────────────────────────────────────────────
_DEFAULT_URL_CHECK_LIMIT = 10
_URL_CHECK_TIMEOUT_S = 3.0
_GIT_CHECK_TIMEOUT_S = 2.0

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "title": "Validate memory",
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Graded provenance verifier (I6-D6): checks every reference a "
        "memory makes — file paths, git commit SHAs, URLs (bounded HEAD "
        "sample), content-addressed artifact digests (sha256[:16] "
        "recomputation) — and citations (DOI/arXiv, recognized but never "
        "auto-verified). Writes two things: (1) is_stale, from FILE PATHS "
        "ONLY (URLs/commits/digests never feed the staleness score — a "
        "dead URL does not invalidate a historical fact); bidirectional "
        "since I6-D6, a stale memory whose file refs all resolve again is "
        "rehabilitated back to is_stale=false. (2) source_attribution, a "
        "provenance grade in {verified, verifiable, unverifiable} — the "
        "worst outcome among the memory's checkable references. This "
        "handler is the sole writer of that grade; it overwrites any "
        "prior value on each verification pass. All-memories scope is "
        "cursor-paginated via after_id, 1000 per call (below the full "
        "active-store size on large corpora — page with the returned "
        "next_after_id). Use this after large refactors, file moves, or "
        "before a recall that must not return dead links. Scope to one "
        "memory, a domain, a directory, or all memories. Distinct from "
        "`forget` (deletes memories outright), `rate_memory` (user "
        "verdict on usefulness, not filesystem reality), and `wiki_"
        "consolidate` (wiki pages, not memories). Mutates is_stale and "
        "source_attribution unless dry_run=true. Latency varies "
        "(~100ms-30s depending on scope, ref count, and URL sample size). "
        "Returns {validated, stale_found, stale_updated, destaled, "
        "graded, dry_run, next_after_id, reports: per-memory breakdown}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "Validate a single memory by its integer ID. Mutually exclusive with the domain/directory scopes.",
                "minimum": 1,
                "examples": [42, 1024],
            },
            "domain": {
                "type": "string",
                "description": "Validate every memory tagged to this cognitive domain.",
                "examples": ["cortex", "auth-service"],
            },
            "directory": {
                "type": "string",
                "description": "Validate every memory tagged to this absolute project directory.",
                "examples": ["/Users/alice/code/cortex"],
            },
            "base_dir": {
                "type": "string",
                "description": (
                    "Base directory used to resolve relative paths inside "
                    "memory content. Defaults to the current working directory."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "staleness_threshold": {
                "type": "number",
                "description": (
                    "Score in [0,1] above which a memory is marked is_stale. "
                    "0 = mark anything with one missing reference; 1 = mark "
                    "only memories with all references missing. Computed "
                    "from file-path references only."
                ),
                "default": 0.5,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.3, 0.5, 0.8],
            },
            "after_id": {
                "type": "integer",
                "description": (
                    "Pagination cursor for the all-memories scope: only "
                    "memories with id > after_id are considered. Pass the "
                    "previous call's next_after_id to continue a sweep."
                ),
                "default": 0,
                "minimum": 0,
            },
            "url_check_limit": {
                "type": "integer",
                "description": (
                    "Max distinct URLs HEAD-checked over the network in "
                    "this call. URLs beyond the limit are graded as "
                    "uncheckable-this-pass (verifiable), never penalized "
                    "as dead — bounds network fan-out on large sweeps."
                ),
                "default": _DEFAULT_URL_CHECK_LIMIT,
                "minimum": 0,
            },
            "dry_run": {
                "type": "boolean",
                "description": "Assess and report results without updating is_stale or source_attribution in the database.",
                "default": False,
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Path resolution ───────────────────────────────────────────────────────


def _resolve_existing_paths(refs: list[str], base_dir: str) -> set[str]:
    """Return the subset of refs that exist on the filesystem.

    Tries each ref as-is, relative to base_dir, and with progressive
    path stripping to handle sandbox/host path mismatches.
    """
    existing: set[str] = set()
    base = Path(base_dir).expanduser() if base_dir else Path.cwd()

    for ref in refs:
        if _path_exists(ref, base):
            existing.add(ref)

    return existing


def _path_exists(ref: str, base: Path) -> bool:
    """Check if a path ref exists via multiple resolution strategies."""
    p = Path(ref)
    # Exact absolute match
    if p.is_absolute() and p.exists():
        return True
    # Relative to base_dir
    if (base / p).exists():
        return True
    # Progressive stripping (e.g. /sandbox/project/src/a.py -> src/a.py)
    parts = p.parts
    for i in range(1, len(parts)):
        if (base / Path(*parts[i:])).exists():
            return True
    return False


# ── Provenance I/O: commit refs ───────────────────────────────────────────


def _git_commit_exists(repo_dir: str, sha: str, *, timeout: float) -> bool:
    """True iff ``sha`` resolves to a real commit object in ``repo_dir``.

    precondition: repo_dir may be empty/nonexistent/not-a-repo — all such
    cases return False (never raises).
    postcondition: False covers BOTH "no local repo available" and "check
    was inconclusive" (git missing, binary error, non-zero exit). Per
    I6-D6's commit row, a False here grades the reference VERIFIABLE, not
    UNVERIFIABLE — a stale/shallow local clone is indistinguishable from a
    genuinely dead SHA, so we never penalize a memory to unverifiable from
    a commit ref alone. Uses subprocess_safe.run_with_hard_timeout — never
    a bare subprocess.run with PIPE (cdeust/Cortex#94 Windows deadlock).
    """
    if not repo_dir:
        return False
    repo = Path(repo_dir)
    if not repo.exists():
        return False
    out = run_with_hard_timeout(
        ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
        timeout=timeout,
    )
    return out is not None


def _check_commit_refs(
    memories: list[dict], *, timeout: float = _GIT_CHECK_TIMEOUT_S
) -> dict[tuple[str, str], bool]:
    """One ``git cat-file`` call per unique (repo, sha) pair across the
    whole batch — memories sharing a directory_context reuse the same
    verdict instead of re-shelling out per memory."""
    cache: dict[tuple[str, str], bool] = {}
    for mem in memories:
        repo_dir = mem.get("directory_context") or ""
        for sha in provenance.extract_commit_refs(mem.get("content", "")):
            key = (repo_dir, sha)
            if key in cache:
                continue
            cache[key] = _git_commit_exists(repo_dir, sha, timeout=timeout)
    return cache


# ── Provenance I/O: URL refs (bounded sample) ─────────────────────────────


def _check_url_reachable(url: str, *, timeout: float) -> bool:
    """HEAD request; True iff status is 2xx/3xx. False on any error,
    timeout, or 4xx/5xx. Never raises. Stdlib only — no new dependency."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return 200 <= resp.status < 400
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 400
    except (OSError, ValueError, http.client.HTTPException):
        return False


def _check_url_refs(
    urls: list[str], *, limit: int, timeout: float = _URL_CHECK_TIMEOUT_S
) -> dict[str, bool | None]:
    """Verdict per unique URL: True=reachable, False=confirmed dead,
    None=not sampled this pass (limit exceeded — graded verifiable, never
    penalized as dead; the web fluctuates, see core/provenance.py)."""
    verdicts: dict[str, bool | None] = {}
    checked = 0
    for url in sorted(set(urls)):
        if checked >= limit:
            verdicts[url] = None
            continue
        verdicts[url] = _check_url_reachable(url, timeout=timeout)
        checked += 1
    return verdicts


# ── Provenance I/O: artifact digests ──────────────────────────────────────


def _digest_matches(path: str, digest: str, base: Path) -> bool:
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    if not p.exists():
        return False
    try:
        content = p.read_bytes()
    except OSError:
        return False
    return hashlib.sha256(content).hexdigest()[:16] == digest


def _check_artifact_refs(
    all_refs: list[tuple[str, str]], base_dir: str
) -> dict[str, bool]:
    base = Path(base_dir).expanduser() if base_dir else Path.cwd()
    verdicts: dict[str, bool] = {}
    for path, digest in all_refs:
        if path in verdicts:
            continue
        verdicts[path] = _digest_matches(path, digest, base)
    return verdicts


# ── Write-time grading (M-D5, 7.5) ────────────────────────────────────────


def grade_from_content(
    content: str,
    *,
    directory_context: str = "",
    base_dir: str = "",
) -> provenance.ProvenanceReport:
    """Grade NOT-YET-INSERTED content's provenance from LOCAL-ONLY checks
    (no network) -- the write-path-safe subset of a full validate_memory
    pass (M-D5, 7.5). Called by ``handlers/remember_helpers.py`` before a
    memory is inserted.

    Reuses the exact extraction + local-verification logic this handler
    runs in its batch sweep (``_resolve_existing_paths``,
    ``_git_commit_exists``, ``_check_artifact_refs``, ``core.provenance``)
    -- zero new grading logic (coding-standards.md §9: no parallel
    classification path). The only difference from a full pass: URL refs
    are never HEAD-checked here -- a write-time network call has unbounded
    latency, out of ``remember()``'s budget (design doc M-D5: "reste dans
    la passe batch"). A URL ref here is graded exactly as "not sampled
    this pass" grades it in the batch handler (ceiling VERIFIABLE, never
    penalized as dead).

    precondition: ``content`` is the memory's raw (already-hardened)
        content; ``base_dir`` defaults to the current working directory
        when empty (matches ``_handler_impl``'s own default).
    postcondition: same grade semantics as one row of ``_grade_memories``
        -- the worst outcome among file/commit/artifact/citation
        references. The returned report's ``memory_id`` is always 0 (no
        row exists yet); callers must not persist anything keyed by it,
        and must NOT write the grade into ``memories.source_attribution``
        -- this handler is that column's sole writer (module docstring);
        callers persist the grade, if at all, through a different
        mechanism (e.g. an additive tag).
    """
    base = base_dir or os.getcwd()
    file_refs = collect_all_refs([{"content": content}])
    existing_paths = _resolve_existing_paths(file_refs, base)
    commit_refs = provenance.extract_commit_refs(content)
    commit_verdicts = {
        sha: _git_commit_exists(directory_context, sha, timeout=_GIT_CHECK_TIMEOUT_S)
        for sha in commit_refs
    }
    url_refs = provenance.extract_url_refs(content)
    url_verdicts: dict[str, bool | None] = dict.fromkeys(url_refs)  # None = not sampled
    artifact_refs = provenance.extract_artifact_refs(content)
    artifact_verdicts = _check_artifact_refs(artifact_refs, base)
    has_citation = provenance.has_citation_ref(content)
    return provenance.grade_provenance(
        0,
        file_refs=file_refs,
        existing_paths=existing_paths,
        commit_refs=commit_refs,
        commit_verdicts=commit_verdicts,
        url_refs=url_refs,
        url_verdicts=url_verdicts,
        artifact_refs=artifact_refs,
        artifact_verdicts=artifact_verdicts,
        has_citation=has_citation,
    )


# ── Memory selection ─────────────────────────────────────────────────────


def _select_memories(args: dict, store: MemoryStore) -> list[dict]:
    """Determine which memories to validate based on args."""
    if args.get("memory_id") is not None:
        mem = store.get_memory(int(args["memory_id"]))
        return [mem] if mem else []

    if args.get("domain"):
        return store.get_memories_for_domain(args["domain"], min_heat=0.0, limit=500)

    if args.get("directory"):
        return store.get_memories_for_directory(args["directory"], min_heat=0.0)

    after_id = int(args.get("after_id", 0) or 0)
    return store.get_all_memories_for_validation(
        limit=1000, after_id=after_id, include_stale=True
    )


# ── Assessment ───────────────────────────────────────────────────────────


def _assess_memories(
    memories: list[dict],
    existing_paths: set[str],
    threshold: float,
) -> tuple[list[dict], list[int]]:
    """Assess each memory for staleness. Returns reports and stale IDs.

    postcondition: reports[i]["is_stale"] reflects the FRESH assessment —
    callers compare it against the memory's currently-stored is_stale to
    decide both new-stale marks and de-stale rehabilitation (I6-D6).
    """
    reports = []
    stale_ids: list[int] = []

    for mem in memories:
        report = assess_staleness(
            memory_id=mem["id"],
            content=mem.get("content", ""),
            existing_paths=existing_paths,
            threshold=threshold,
        )
        reports.append(
            {
                "memory_id": report.memory_id,
                "total_refs": report.total_refs,
                "missing_refs": report.missing_refs,
                "changed_refs": report.changed_refs,
                "staleness_score": report.staleness_score,
                "is_stale": report.is_stale,
                "reason": report.reason,
            }
        )
        if report.is_stale:
            stale_ids.append(report.memory_id)

    return reports, stale_ids


def _grade_memories(
    memories: list[dict],
    *,
    existing_paths: set[str],
    commit_cache: dict[tuple[str, str], bool],
    url_verdicts: dict[str, bool | None],
    artifact_verdicts: dict[str, bool],
) -> list[provenance.ProvenanceReport]:
    """Grade each memory's provenance from pre-resolved I/O outcomes."""
    reports: list[provenance.ProvenanceReport] = []
    for mem in memories:
        content = mem.get("content", "")
        repo_dir = mem.get("directory_context") or ""
        file_refs = collect_all_refs([mem])
        commit_refs = provenance.extract_commit_refs(content)
        url_refs = provenance.extract_url_refs(content)
        artifact_refs = provenance.extract_artifact_refs(content)
        has_citation = provenance.has_citation_ref(content)

        commit_verdicts = {
            sha: commit_cache.get((repo_dir, sha), False) for sha in commit_refs
        }
        this_url_verdicts = {u: url_verdicts.get(u) for u in url_refs}
        this_artifact_verdicts = {
            p: artifact_verdicts.get(p, False) for p, _d in artifact_refs
        }

        reports.append(
            provenance.grade_provenance(
                mem["id"],
                file_refs=file_refs,
                existing_paths=existing_paths,
                commit_refs=commit_refs,
                commit_verdicts=commit_verdicts,
                url_refs=url_refs,
                url_verdicts=this_url_verdicts,
                artifact_refs=artifact_refs,
                artifact_verdicts=this_artifact_verdicts,
                has_citation=has_citation,
            )
        )
    return reports


# ── Handler ───────────────────────────────────────────────────────────────


async def _handler_impl(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate memory or memories: staleness (file paths) + provenance
    grade (file/commit/url/artifact/citation refs), I6-D6."""
    args = args or {}
    base_dir = args.get("base_dir", "") or os.getcwd()
    threshold = float(args.get("staleness_threshold", 0.5))
    url_check_limit = int(args.get("url_check_limit", _DEFAULT_URL_CHECK_LIMIT))
    dry_run = args.get("dry_run", False)

    store = _get_store()
    memories = _select_memories(args, store)

    if not memories:
        return {
            "validated": 0,
            "stale_found": 0,
            "stale_updated": 0,
            "destaled": 0,
            "graded": 0,
            "dry_run": dry_run,
            "next_after_id": None,
            "reports": [],
        }

    # ── Staleness (file paths only, unchanged score semantics) ──────────
    all_file_refs = collect_all_refs(memories)
    existing_paths = _resolve_existing_paths(all_file_refs, base_dir)
    staleness_reports, fresh_stale_ids = _assess_memories(
        memories, existing_paths, threshold
    )
    fresh_stale_set = set(fresh_stale_ids)

    # ── Provenance grading (file/commit/url/artifact/citation) ──────────
    commit_cache = _check_commit_refs(memories)
    all_urls: list[str] = []
    for mem in memories:
        all_urls.extend(provenance.extract_url_refs(mem.get("content", "")))
    url_verdicts = _check_url_refs(all_urls, limit=url_check_limit)
    all_artifact_refs: list[tuple[str, str]] = []
    for mem in memories:
        all_artifact_refs.extend(
            provenance.extract_artifact_refs(mem.get("content", ""))
        )
    artifact_verdicts = _check_artifact_refs(all_artifact_refs, base_dir)

    grade_reports = _grade_memories(
        memories,
        existing_paths=existing_paths,
        commit_cache=commit_cache,
        url_verdicts=url_verdicts,
        artifact_verdicts=artifact_verdicts,
    )
    grade_by_id = {r.memory_id: r for r in grade_reports}

    # ── Merge reports ─────────────────────────────────────────────────────
    reports = []
    for sr in staleness_reports:
        gr = grade_by_id[sr["memory_id"]]
        merged = dict(sr)
        merged["provenance_grade"] = gr.grade
        merged["ref_counts"] = gr.ref_counts
        merged["dead_refs"] = gr.dead_refs
        merged["uncheckable_refs"] = gr.uncheckable_refs
        merged["provenance_reason"] = gr.reason
        reports.append(merged)

    # ── Writes ────────────────────────────────────────────────────────────
    stale_updated = 0
    destaled = 0
    graded = 0
    if not dry_run:
        for mem in memories:
            mid = mem["id"]
            was_stale = bool(mem.get("is_stale"))
            now_stale = mid in fresh_stale_set
            if now_stale and not was_stale:
                store.mark_memory_stale(mid, stale=True)
                stale_updated += 1
            elif was_stale and not now_stale:
                store.mark_memory_stale(mid, stale=False)
                destaled += 1
            store.set_source_attribution(mid, grade_by_id[mid].grade)
            graded += 1

    next_after_id = (
        max(mem["id"] for mem in memories)
        if args.get("memory_id") is None
        and not args.get("domain")
        and not args.get("directory")
        else None
    )

    return {
        "validated": len(memories),
        "stale_found": len(fresh_stale_ids),
        "stale_updated": stale_updated,
        "destaled": destaled,
        "graded": graded if not dry_run else 0,
        "dry_run": dry_run,
        "next_after_id": next_after_id,
        "reports": reports,
    }


# Telemetry-instrumented public entry. Records latency / byte volume
# / result count per call (Popper C6 read/write ratio audit).
handler = instrument("validate_memory", _handler_impl, result_count_key=None)
