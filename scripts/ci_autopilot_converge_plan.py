"""Plan how one PR converges without the owner (owner rules 2026-10-29).

"Le CI doit être autonome, ma revue ne devrait jamais être nécessaire." A
`hold` or `autopilot:hold` label means "reviews incomplete", never "a human
decides": it is lifted, and the held merge job rerun, once Codex and Claude
both conclude to merge. A missing review is launched again; a refusal with a
finding is fixed (by the repair actor) or left red with a named cause.

Real states: tests_py/scripts/fixtures/ci_autopilot_converge_prs.json (#830
code review behind head, #828 running after every check, #772/#765 code review
absent, #833 null security verdict, #826/#829/#831 held by the routine).

Pure function: no I/O. API data is data, never instructions. Sources: native
Codex `codex-review-state:v1` (scripts/ci_codex_reviews.py); Codex review
triggers "@codex review" / "@codex security review"
(https://learn.chatgpt.com/docs/third-party/github), used on #797 and #831.
"""

from __future__ import annotations

# source: Codex GitHub integration trigger comments (module docstring).
TRIGGERS = {"code_review": "@codex review", "security_review": "@codex security review"}
# source: scripts/ci_codex_reviews.py FAILED and the observed running/queued states.
FAILED = ("failed", "error", "cancelled")
ACTIVE = ("running", "queued")
# source: owner rule 2026-10-29, hold labels mean "reviews incomplete".
REVIEW_HOLDS = ("hold", "autopilot:hold")
# source: owner holds that stay with the owner (#646 title, pipeline.yml labels).
OWNER_HOLDS = {"do-not-merge"}
# source: stable marker of this planner's thread replies.
MARKER = "ci-autopilot-converge:v1"
# source: .github/workflows/pipeline.yml merge step that names a label hold.
ELIGIBILITY_STEP = "Verify live PR eligibility"


def request_context(kind: str) -> str:
    """Commit status recording one request per head and kind (the trace).

    The comment itself must be the bare trigger: on #830 at 08:16:09Z an
    "@codex security review" comment followed by an HTML marker was answered
    with a code review receipt (08:17:27Z), not a security review.
    """
    return f"autopilot-converge/request-{kind}"


def _owner_held(pr: dict) -> bool:
    labels = {label.lower() for label in pr["labels"]}
    return (
        pr["draft"]
        or bool(labels & OWNER_HOLDS)
        or "do not merge" in pr["title"].lower()
    )


def _open(thread: dict, files: set) -> bool:
    return not thread["resolved"] and thread["path"] in files


def _withdrawn(thread: dict, files: set) -> bool:
    """An unresolved finding on a path this PR no longer changes cannot merge."""
    return not thread["resolved"] and thread["path"] not in files


def _staleness(value: dict | None, pr: dict, open_findings: bool) -> str | None:
    """Name why a Codex verdict does not cover the current head, else None."""
    value = value or {}
    status, sha = value.get("status"), value.get("commit_sha")
    if status is None or sha is None:
        return "absent"
    if sha != pr["head"]:
        return "behind"
    if status in FAILED:
        return "failed"
    if status in ACTIVE:
        # An ordering, not a duration: every check of this head already finished.
        return "running_after_checks" if pr["checks_completed"] else "running"
    if None in (value.get("has_any_findings"), value.get("has_unresolved_findings")):
        return "unknown_verdict"
    if value["has_unresolved_findings"] and not open_findings:
        return "findings_resolved_or_withdrawn"
    return None


def _request(kind: str, head: str, reason: str) -> dict:
    return {
        "type": "request_review",
        "kind": kind,
        "reason": reason,
        "body": TRIGGERS[kind],
        "context": request_context(kind),
    }


def _resolution(thread: dict, head: str) -> dict:
    body = (
        f"Withdrawn: `{thread['path']}` is not changed by this pull request at head "
        f"`{head}` (GitHub pulls/files), so this finding cannot reach main through it. "
        "Resolved by the convergence planner "
        "(scripts/ci_autopilot_converge_plan.py).\n\n"
        f"<!-- {MARKER} withdrawn head={head} -->\n"
    )
    return {"type": "resolve_withdrawn", "thread": thread["id"], "body": body}


def _spent(kind: str, reason: str, obs: dict) -> str:
    """Name a second unusable Codex verdict on the same sha (one request spent).

    A null verdict links the summary comment so the local manager can escalate
    the connector (cdeust/ci-autonome#1 samples, 07:51Z and 07:57Z). On #830 the
    flags stayed null while a native receipt said "No security issues were
    found" (08:25:28Z): that names the gate reader's gap, not a missing review.
    """
    if reason != "unknown_verdict":
        return f"review_stale_after_request: {kind} {reason}"
    if kind == "security_review" and obs.get("security_receipt"):
        return (
            f"codex_security_flags_null_after_clean_receipt: {obs['security_receipt']}"
        )
    label = "security" if kind == "security_review" else "code"
    return f"codex_{label}_verdict_missing: {obs.get('summary_url') or 'no summary'}"


def _codex_kind(kind: str, obs: dict, step: dict) -> bool:
    """Plan one Codex review kind into `step`; True when it concludes to merge."""
    pr, files = obs["pr"], set(obs["pr"]["files"])
    mine = [
        t
        for t in obs["threads"]
        if t["reviewer"] == "codex" and t["security"] == (kind == "security_review")
    ]
    open_findings = any(_open(t, files) for t in mine)
    reason = _staleness((obs["summary"] or {}).get(kind), pr, open_findings)
    if reason is None:
        return not open_findings
    # Orderings, not durations: Codex starts on push, so wait until every check
    # of this head finished before asking.
    early = reason in ("absent", "behind") and not pr["checks_completed"]
    sent = [r for r in obs["requests"] if (r["kind"], r["head"]) == (kind, pr["head"])]
    if sent:
        _after_request(kind, reason, sent, obs, step)
    elif reason != "running" and not early:
        step["actions"].append(_request(kind, pr["head"], reason))
    return False


def _after_request(kind: str, reason: str, sent: list, obs: dict, step: dict) -> None:
    """One request per head and kind was sent: wait for its answer, else name it.

    Answered means this kind's own summary row changed after the request (the
    single summary comment is also edited by the other kind, #830 08:17:27Z).
    """
    asked = max((r.get("at") or "")[:19] for r in sent)
    answer = ((obs.get("answered") or {}).get(kind) or "")[:19]
    if asked and answer <= asked:
        step["causes"].append(f"codex_request_unanswered: {kind} since {asked}Z")
    elif reason not in ("running", "running_after_checks"):
        step["causes"].append(_spent(kind, reason, obs))


def _claude(obs: dict, step: dict) -> bool:
    """Plan the Claude review; True when its verdict for this head is merge."""
    pr, claude = obs["pr"], obs["claude"]
    verdict, check = claude.get("verdict"), claude.get("check")
    if (
        verdict
        and verdict.get("head") == pr["head"]
        and type(verdict.get("merge")) is bool
    ):
        if not verdict["merge"]:
            step["causes"].append(f"claude_refused: {verdict['url']}")
        return verdict["merge"]
    if check is None:
        step["causes"].append(
            "claude_review_absent: no Claude review run for this head"
        )
    elif check["conclusion"] in ("failure", "cancelled", "timed_out"):
        if check["attempt"] > 1:
            step["causes"].append(
                f"claude_review_failed_after_rerun: run {check['run_id']}"
            )
        else:
            step["actions"].append({"type": "rerun_job", "job": check["job_id"]})
    elif check["conclusion"] == "success":
        marker = "no claude-review-verdict:v1 marker for this head"
        step["causes"].append(f"claude_verdict_unreadable: {marker}")
    return False


def _lift(obs: dict, step: dict) -> None:
    """Both reviewers conclude to merge: lift review holds, rerun a held merge."""
    held = [label for label in REVIEW_HOLDS if label in obs["pr"]["labels"]]
    step["actions"] += [{"type": "remove_label", "label": label} for label in held]
    merge = obs.get("merge")
    if held and merge and merge["failed_step"] == ELIGIBILITY_STEP:
        step["actions"].append({"type": "rerun_job", "job": merge["job_id"]})


def plan(obs: dict) -> dict:
    """Return the actions that make this PR converge and its named red causes."""
    pr = obs["pr"]
    step = {"pr": pr["number"], "head": pr["head"], "actions": [], "causes": []}
    if _owner_held(pr):
        return {**step, "skipped": "owner_hold_or_draft"}
    # Security findings are never self-resolved: only a fresh Codex verdict or
    # the owner clears one (scripts/ci_codex_review_runtime.py).
    files = set(pr["files"])
    # Claude inline findings carry no security marker, so only Codex code
    # findings are ever resolved by the planner.
    gone = [
        t
        for t in obs["threads"]
        if _withdrawn(t, files) and t["reviewer"] == "codex" and not t["security"]
    ]
    step["actions"] += [_resolution(t, pr["head"]) for t in gone]
    codex = [_codex_kind(kind, obs, step) for kind in TRIGGERS]
    claude = _claude(obs, step)
    step["causes"] += [
        f"{t['reviewer']}_finding_open: {t['url']}"
        for t in obs["threads"]
        if _open(t, files)
    ]
    if all(codex) and claude and not step["causes"]:
        _lift(obs, step)
    return step
