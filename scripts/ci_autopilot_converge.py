#!/usr/bin/env python3
"""Make every open PR converge without the owner, or name why it is red.

Owner rules 2026-10-29: "Le CI doit être autonome, ma revue ne devrait jamais
être nécessaire"; `hold`/`autopilot:hold` mean "reviews incomplete". Reads live
GitHub data (scripts/ci_autopilot_converge_observe.py), plans with
scripts/ci_autopilot_converge_plan.py and, with --apply, requests a stale
Codex review, reruns a failed Claude review, resolves code findings on
withdrawn paths, lifts the review holds and reruns the held merge job once
Codex and Claude both conclude to merge, and publishes the remaining named
red cause as the commit status `autopilot-converge` on the PR head. It never
merges itself, never resolves a security finding, never touches an owner
hold (`do-not-merge`, "do not merge" title), a draft or a fork.

Sources: GitHub REST issues/comments, issues/labels, statuses, actions/jobs
rerun; GraphQL addPullRequestReviewThreadReply and resolveReviewThread.
Exit 1 when any PR is left red, so the scheduled run is red with its causes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_autopilot_converge_observe import observe_pull, run_gh  # noqa: E402
from ci_autopilot_converge_plan import plan  # noqa: E402

# source: gh pr list --limit; fail closed instead of truncating (ci_autopilot.py).
PR_LIMIT = 1000
# source: GitHub commit status description limit, REST "Create a commit status".
STATUS_LENGTH = 140
# source: GitHub GraphQL mutations addPullRequestReviewThreadReply, resolveReviewThread.
REPLY = (
    "mutation($t:ID!,$b:String!){addPullRequestReviewThreadReply("
    "input:{pullRequestReviewThreadId:$t,body:$b}){comment{id}}}"
)
RESOLVE = (
    "mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}"
)
# Module-level seam so tests replace every GitHub call at once.
gh = run_gh


def _status(repo: str, result: dict) -> None:
    red = bool(result["causes"])
    text = "; ".join(result["causes"]) if red else "converging: no named red cause"
    state = "failure" if red else "success"
    shown = text[:STATUS_LENGTH].rstrip()
    published = result.get("published") or {}
    if (published.get("state"), (published.get("description") or "").rstrip()) == (
        state,
        shown,
    ):
        return  # Unchanged: commit statuses are capped per sha and context.
    gh(
        "api",
        "--method",
        "POST",
        f"repos/{repo}/statuses/{result['head']}",
        "-f",
        f"state={state}",
        "-f",
        "context=autopilot-converge",
        "-f",
        f"description={shown}",
        "-f",
        f"target_url=https://github.com/{repo}/pull/{result['pr']}",
    )


def _trace(repo: str, head: str, action: dict) -> None:
    """Record the request on the head so it is sent once per sha and kind."""
    gh(
        "api",
        "--method",
        "POST",
        f"repos/{repo}/statuses/{head}",
        "-f",
        "state=success",
        "-f",
        f"context={action['context']}",
        "-f",
        f"description=requested {action['kind']} ({action['reason']})",
    )


def _act(repo: str, target: tuple, action: dict, token: str | None) -> None:
    number, head = target
    kind = action["type"]
    if kind == "request_review":
        # Trace first: a failed comment then reads as an unanswered request.
        _trace(repo, head, action)
        body = ("--body-file", "-")
        gh(
            "pr",
            "comment",
            number,
            "--repo",
            repo,
            *body,
            token=token,
            stdin=action["body"],
        )
    elif kind == "resolve_withdrawn":
        thread = f"t={action['thread']}"
        gh(
            "api",
            "graphql",
            "-f",
            f"query={REPLY}",
            "-f",
            thread,
            "-f",
            f"b={action['body']}",
        )
        gh("api", "graphql", "-f", f"query={RESOLVE}", "-f", thread)
    elif kind == "remove_label":
        label = action["label"].replace(":", "%3A")
        gh("api", "--method", "DELETE", f"repos/{repo}/issues/{number}/labels/{label}")
    elif kind == "rerun_job":
        gh(
            "api",
            "--method",
            "POST",
            f"repos/{repo}/actions/jobs/{action['job']}/rerun",
        )


def apply(repo: str, result: dict, request_token: str | None) -> None:
    for action in result["actions"]:
        _act(repo, (str(result["pr"]), result["head"]), action, request_token)
    _status(repo, result)


def _open_pulls(repo: str, only: int | None) -> list:
    fields = (
        "number,title,isDraft,isCrossRepository,headRefOid,labels,statusCheckRollup"
    )
    limit = ("--limit", str(PR_LIMIT))
    pulls = gh(
        "pr", "list", "--repo", repo, "--state", "open", *limit, "--json", fields
    )
    if len(pulls) == PR_LIMIT:
        raise RuntimeError("PR intake limit reached; never silently truncate")
    pulls = [p for p in pulls if not p["isCrossRepository"]]
    return [p for p in pulls if only is None or p["number"] == only]


def name_requester(result: dict, token: str | None) -> dict:
    """Name what is missing when a spent request came from the workflow bot.

    Codex review triggers observed on #797 and #831 came from the owner's user
    account; a github-actions[bot] request is not proven to start a review.
    """
    if token:
        return result
    suffix = " (requested by the workflow token; CODEX_REQUEST_TOKEN unset)"
    spent = (
        "review_stale_after_request",
        "codex_security_verdict_missing",
        "codex_code_verdict_missing",
    )
    causes = [c + suffix if c.startswith(spent) else c for c in result["causes"]]
    return {**result, "causes": causes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="cdeust/Cortex")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    red = False
    token = os.environ.get("CODEX_REQUEST_TOKEN") or None
    for pull in _open_pulls(args.repo, args.pr):
        result = _guarded(args, pull, token)
        red = red or bool(result["causes"])
        shown = [{k: v for k, v in a.items() if k != "body"} for a in result["actions"]]
        print(json.dumps({**result, "actions": shown}, sort_keys=True))
    return 1 if red else 0


# source: failures seen or reviewed on #834: API errors, malformed markers,
# deleted thread roots (IndexError) and non-object review values.
FAILURES = (
    subprocess.CalledProcessError,
    LookupError,
    TypeError,
    ValueError,
    AttributeError,
)


def _guarded(args, pull: dict, token: str | None) -> dict:
    """One PR's failure never stops the others; it is named red on its head."""
    stage = "observe_failed"
    try:
        obs = observe_pull(args.repo, pull)
        result = name_requester(plan(obs), token)
        result["published"] = obs.get("published")
        stage = "apply_failed"
        if args.apply and "skipped" not in result:
            apply(args.repo, result, token)
        return result
    except FAILURES as exc:
        head = pull.get("headRefOid", "")
        cause = f"{stage}: {type(exc).__name__}"
        failed = {"pr": pull["number"], "head": head, "actions": [], "causes": [cause]}
        if args.apply and head:
            try:
                _status(args.repo, failed)
            except FAILURES:
                pass  # The workflow log still names the cause; the pass goes on.
        return failed


if __name__ == "__main__":
    sys.exit(main())
