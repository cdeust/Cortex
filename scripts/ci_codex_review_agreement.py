"""Gate state for one head: both native Codex kinds, then the Claude verdict.

Owner rule 2026-10-29 (verbatim): "until the review of codex and claude (done
autonomously) are there, it cannot merge, the hold should be removed after
reviewers agree on merging". Rules of the Cortex convergence planner
(https://github.com/cdeust/Cortex/pull/834, scripts/ci_autopilot_converge_plan.py).
The Claude verdict is the marker claude-review.yml asks for (source.json adaptation
claude-review-verdict-marker); GraphQL author claude/Bot, prD evidence. Pure: no I/O.
"""

from __future__ import annotations

import re
from typing import Any

from ci_codex_review_runtime import EvidenceError, _json
from ci_codex_review_comments import BLOCKED_REASONS, BLOCKING, BOT, MISSING
from ci_codex_review_comments import STAMP_PATTERN, UNRECOGNIZED, _authenticate_editor

Record = dict[str, Any]
CLAUDE = "claude[bot]"
VERDICT = re.compile(r"^<!-- claude-review-verdict:v1 (\{.*\}) -->$", re.MULTILINE)
CLAUDE_CAUSES = {"missing": "claude_verdict_missing", "refused": "claude_refused",
                 "unreadable": "claude_verdict_unreadable"}
# Rule D5 (ci_codex_review_comments.DEPENDABOT): no Claude review exists there.
AGREED = ("merge", "not_applicable_dependabot")
# Rule D6, 2026-10-29: a failed kind whose latest Codex Bot comment is a usage-limit
# notice waits for quota, it is no finding. Real notices: cdeust/ci-autonome PR9
# comment6497426761 ("has reached its Codex usage limits"), cdeust/ai-architect-
# mcp-spec PR164 comment6497379059 and ai-architect-mcp-codebase PR469
# comment6497357065 ("You have reached your Codex usage limits for code reviews").
QUOTA = re.compile(r"\breached (?:its|your) Codex usage limits\b")
CODEX_CAUSES = {
    "pending": "codex_{}_verdict_missing", "failed": "codex_{}_review_failed",
    "unresolved": "codex_{}_findings_unresolved", MISSING: "codex_{}_verdict_missing",
    UNRECOGNIZED: "codex_{}_receipt_unrecognized", "quota": "codex_quota_exhausted",
}


def _verdict(comment: Record, sha: str) -> bool | None:
    """The merge flag of one Claude App marker for this head, else None."""
    user, body, stamp = comment.get("user"), comment.get("body"), comment.get("updated_at")
    if not isinstance(user, dict) or (user.get("login"), user.get("type")) != (CLAUDE, "Bot"):
        return None
    if not isinstance(body, str) or body.count("claude-review-verdict:v1") != 1:
        return None
    found = VERDICT.findall(body)
    if len(found) != 1 or not isinstance(stamp, str) or not STAMP_PATTERN.fullmatch(stamp):
        return None
    try:
        value = _json(found[0])
    except EvidenceError:
        return None  # A malformed marker reads as absent, never as a verdict.
    if not isinstance(value, dict) or set(value) != {"head", "merge"}:
        return None
    return value["merge"] if value["head"] == sha and type(value["merge"]) is bool else None


def claude_verdict(comments: list[Record], sha: str) -> Record:
    """Latest Claude verdict for this head; one edited by anyone else is unreadable."""
    marked = [(c, merge) for c in comments if (merge := _verdict(c, sha)) is not None]
    if not marked:
        verdict = "not_applicable_dependabot" if getattr(comments, "dependabot", False) is True else "missing"
        return {"verdict": verdict, "comment_id": 0}
    comment, merge = max(marked, key=lambda row: (row[0]["updated_at"], row[0]["id"]))
    try:
        _authenticate_editor(comment, "claude")
    except EvidenceError:
        return {"verdict": "unreadable", "comment_id": comment["id"]}
    return {"verdict": "merge" if merge else "refused", "comment_id": comment["id"]}


def _quota(comments: list[Record]) -> bool:
    """True when the latest comment of the Codex Bot is a usage-limit notice."""
    stamped = [
        c for c in comments
        if (c.get("user") or {}).get("login") == BOT and (c.get("user") or {}).get("type") == "Bot"
        and isinstance(c.get("updated_at"), str) and STAMP_PATTERN.fullmatch(c["updated_at"])
    ]
    if not stamped:
        return False
    latest = max(stamped, key=lambda c: (c["updated_at"], c["id"]))
    return isinstance(latest.get("body"), str) and QUOTA.search(latest["body"]) is not None


def conclude(states: list[str] | None, comments: list[Record], sha: str) -> Record:
    """Gate state for the head: both Codex kinds (None: no summary), then Claude."""
    claude = claude_verdict(comments, sha)
    verdict, codex = claude["verdict"], list(states or ["pending", "pending"])
    if "failed" in codex and _quota(comments):
        codex = ["quota" if state == "failed" else state for state in codex]
    causes = list(dict.fromkeys(
        CODEX_CAUSES[state].format(kind)
        for kind, state in zip(("code", "security"), codex)
        if state != "success"
    )) + ([CLAUDE_CAUSES[verdict]] if verdict not in AGREED else [])
    if any(s in BLOCKING for s in codex):
        state = "blocked", next((r for s, r in BLOCKED_REASONS if s in codex), "review_unresolved")
    elif verdict in ("refused", "unreadable"):
        state = "blocked", CLAUDE_CAUSES[verdict]
    elif "quota" in codex:
        state = "pending", CODEX_CAUSES["quota"]
    elif "pending" in codex:
        state = "pending", "review_pending" if states else "review_missing"
    elif verdict == "missing":
        state = "pending", CLAUDE_CAUSES[verdict]
    else:
        state = "success", "reviews_complete"
    complete = all(s in ("success", "unresolved") for s in codex)
    return dict(state=state[0], reason=state[1], causes=causes, claude=claude,
                reviews_complete=complete and verdict in (*AGREED, "refused"))
