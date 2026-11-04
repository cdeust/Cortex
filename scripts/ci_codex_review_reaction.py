"""Codex's 👍 reaction as the verdict of a clean security review with null flags.

Source: the Codex summary text, "Codex reacts with 👀 while any review is running,
comments if it has suggestions, and reacts with 👍 once all reviews finish with
no findings." Observed from 2026-10-31 on: the 👍 is present on every PR Codex
reviewed since then with no findings (cortex-viz PR218 06:13:28Z, PR219 and
PR220 07:38:47Z, PR216; Cortex PR838, PR840, PR846, PR847) and absent on every
PR reviewed before (cortex-viz PR207, PR212, PR217 of 2026-10-29). The
no-issues receipt comment that `security_receipt` reads was not posted on any
of them, so a clean review left `codex_security_verdict_missing` on every one
(cortex-viz PR216 run of 2026-11-03). Port of cdeust/Cortex PR847
(scripts/ci_codex_review_comments.py resolve_no_findings), 2026-11-03.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

Record = dict[str, Any]


def _runtime():
    """The runtime module, resolved on use (the reader preloads its exact copy)."""
    import ci_codex_review_runtime as runtime  # noqa: PLC0415 - keeps the import graph acyclic

    return runtime


def _comments():
    import ci_codex_review_comments as comments  # noqa: PLC0415 - same reason

    return comments

# source: Codex summary 6600075171 (Cortex PR848): one table row per review on
# the reviewed head, each with a Completed stamp and the short commit.
COMPLETED_ROW = re.compile(
    r"^\|[^|\n]*\*\*(Code|Security) Review\*\* \| ✅ \*\*Completed\*\* "
    r'<relative-time datetime="([^"]+)"[^|\n]*\| `([0-9a-f]{7,40})` \|',
    re.M,
)
# source: the summary lists one Code Review row and one Security Review row.
REVIEW_KINDS = ("Code", "Security")
# source: runtime.FINDING and runtime._announced; any finding text voids the clean path.
FINDING_TEXT = ("\n### Security findings\n", "<!-- codex-security-review-finding:v1 -->")


def _stamp(value: Any) -> datetime:
    if not isinstance(value, str) or _comments().STAMP_PATTERN.fullmatch(value) is None:
        raise _runtime().EvidenceError("protocol")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:  # shape-valid, calendar-invalid (month 13)
        raise _runtime().EvidenceError("protocol") from exc


def _completed_here(target, review, metadata) -> bool:
    """The review and the security metadata both name this PR's reviewed head."""
    repo, pr, sha = target
    found = (review.get("status"), review.get("commit_sha")) + tuple(
        metadata.get(k) if isinstance(metadata, dict) else None
        for k in ("repository", "pullRequestNumber", "headSha", "status")
    )
    return found == ("completed", sha, repo, pr, sha, "completed")


# source: Cortex PR846 +1 at 2026-11-03T00:23:49Z, after its last head's Security
# Review row of 00:23:45.38Z and five pushes: Codex re-dates its +1 per head. The
# reactions API reports that user with type "User", so only the login is read.
# https://docs.github.com/en/rest/reactions/reactions#list-reactions-for-an-issue
def _codex_reactions(repo: str, pr: int) -> dict[str, datetime]:
    pages = _runtime()._api(f"repos/{repo}/issues/{pr}/reactions", paginate=True)
    if not isinstance(pages, list) or any(not isinstance(p, list) for p in pages):
        raise _runtime().EvidenceError("protocol")
    rows = [row for page in pages for row in page]
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("content"), str)
        or not isinstance(row.get("user"), dict)
        or not isinstance(row["user"].get("login"), str)
        for row in rows
    ):
        raise _runtime().EvidenceError("protocol")
    return {
        row["content"]: _stamp(row.get("created_at"))
        for row in rows
        if row["user"]["login"] == _comments().BOT
    }


def _unresolved_findings(repo: str, pr: int, sha: str) -> bool:
    """Native Codex finding threads of the PR that the owner has not resolved."""
    if repo.count("/") != 1:
        raise _runtime().EvidenceError("protocol")
    owner, name = repo.split("/")
    fields = dict(query=_runtime().THREAD_QUERY, owner=owner, name=name, number=pr)
    pages = _runtime()._api("graphql", paginate=True, fields=fields)
    return not all(_runtime()._thread_states(pages, sha, owner).values())


def resolve_no_findings(target, body, review, metadata):
    """A null verdict after completion is clean only with Codex's +1 not earlier
    than both Completed rows of this summary for this head (second precision:
    reactions carry seconds, rows microseconds), no 👀 left, no finding text in
    the summary and no unresolved native finding thread. A commit date would
    not do: a later push of an older commit keeps its date (Cortex PR847 review).
    """
    repo, pr, sha = target
    flags = (review.get("has_any_findings"), review.get("has_unresolved_findings"))
    if flags != (None, None) or not _completed_here(target, review, metadata):
        return None
    if any(marker in body for marker in FINDING_TEXT):
        return None
    rows = COMPLETED_ROW.findall(body)
    if sorted(kind for kind, _, _ in rows) != sorted(REVIEW_KINDS):
        return None
    if any(not sha.startswith(short) for _, _, short in rows):
        return None
    finished = max(_stamp(stamp) for _, stamp, _ in rows).replace(microsecond=0)
    marks = _codex_reactions(repo, pr)
    if "eyes" in marks or "+1" not in marks or marks["+1"] < finished:
        return None
    if _unresolved_findings(repo, pr, sha):
        return None
    return {
        "state": "success",
        "source": "github_reaction",
        "reacted_at": marks["+1"].strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def reaction_verdict(proof, target, body, review, metadata):
    """The receipt's `verdict_missing` yields to the reaction; anything else stands."""
    if proof is None or proof.get("state") != _comments().MISSING:
        return proof
    return resolve_no_findings(target, body, review, metadata) or proof
