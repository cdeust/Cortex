#!/usr/bin/env python3
"""Count the Claude reviews a pull request already received and apply the cap.

Runs from the trusted default-branch checkout of claude-review.yml, before the
review action. It reads workflow-run metadata only: no PR content, no comment
text. A review counts when its run is a success of the same PR and the action
step ("PR Review") itself succeeded, so runs that skipped the action because
the cap was reached do not count as reviews.

Writes `round`, `cap`, `skip` and `reviewed_sha` to $GITHUB_OUTPUT. At the cap
no fourth review runs: the accepted part merges, the rest leaves the PR for a
refinement PR with a new budget. The label `claude-rereview` raises the cap by one
(a fourth review, never a fifth), however long the label stays attached (ADR-1119).
Any API or protocol error exits non-zero: no silent fallback to "review".

Sources: https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow
https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from typing import Any

Record = dict[str, Any]
Gh = Callable[[list[str]], str]

# source: owner decision 2026-11-04 after Cortex PR 856: 20 automatic Claude
# reviews, 22 comments saying "nothing blocks merge", Codex converged in 3
# (ADR-1119).
CAP = 3
BYPASS_LABEL = "claude-rereview"
EXHAUSTED = (
    f"{CAP} of {CAP} reviews used. A fourth review is not run: merge the accepted "
    "part, remove the rest from this PR and send it to a new refinement PR "
    f"(new budget). The label {BYPASS_LABEL} allows one more review (ADR-1119)."
)
# The step of claude-review.yml that runs the action; the test pins this name.
ACTION_STEP = "PR Review"
SHA = re.compile(r"[0-9a-f]{40}")
# source: GitHub REST per_page maximum.
PER_PAGE = 100
# source: operational bound on one `gh api` call, far above its usual second.
GH_TIMEOUT_SECONDS = 60


class BudgetError(ValueError):
    """The run metadata does not have the documented shape."""


def gh_api(args: list[str]) -> str:
    done = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=GH_TIMEOUT_SECONDS,
    )
    return done.stdout


def _lines(text: str) -> list[Record]:
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise BudgetError("protocol")
    return rows


def candidate_runs(gh: Gh, repo: str, pr: int, run_id: int, head_ref: str):
    jq = (
        ".workflow_runs[] | {id, conclusion, head_sha, created_at, "
        "prs: [.pull_requests[].number]}"
    )
    text = gh(
        [
            f"repos/{repo}/actions/workflows/claude-review.yml/runs",
            "--method",
            "GET",
            "--paginate",
            "--jq",
            jq,
            "-f",
            "event=pull_request",
            "-f",
            f"branch={head_ref}",
            "-f",
            f"per_page={PER_PAGE}",
        ]
    )
    return [
        row
        for row in _lines(text)
        if row.get("id") != run_id
        and row.get("conclusion") == "success"
        and pr in row.get("prs", [])
    ]


def ran_the_action(gh: Gh, repo: str, run: Record) -> bool:
    jq = f'[.jobs[].steps[]? | select(.name == "{ACTION_STEP}") | .conclusion]'
    text = gh([f"repos/{repo}/actions/runs/{run['id']}/jobs", "--jq", jq])
    conclusions = json.loads(text)
    if not isinstance(conclusions, list):
        raise BudgetError("protocol")
    return "success" in conclusions


def decide(reviews: list[Record], labels: list[str], cap: int = CAP) -> Record:
    ordered = sorted(reviews, key=lambda run: run["created_at"])
    count = len(ordered)
    # The label grants exactly one more review, however long it stays attached.
    allowed = cap + (1 if BYPASS_LABEL in labels else 0)
    last = ordered[-1]["head_sha"] if ordered else ""
    if last and not SHA.fullmatch(last):
        raise BudgetError("protocol")
    return {
        "round": count + 1,
        "cap": cap,
        "skip": "true" if count >= allowed else "false",
        "reviewed_sha": last,
    }


def budget(gh: Gh, repo: str, pr: int, run_id: int, head_ref: str, labels):
    runs = candidate_runs(gh, repo, pr, run_id, head_ref)
    reviews = [run for run in runs if ran_the_action(gh, repo, run)]
    return decide(reviews, labels)


def main() -> int:
    env = os.environ
    result = budget(
        gh_api,
        env["GH_REPO"],
        int(env["PR"]),
        int(env["RUN_ID"]),
        env["HEAD_REF"],
        json.loads(env.get("LABELS", "[]")),
    )
    with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        for key, value in result.items():
            out.write(f"{key}={value}\n")
    if result["skip"] == "true":
        print(f"::notice title=Claude review budget used::{EXHAUSTED}")
    else:
        print(f"Claude review {result['round']} of {result['cap']}: go")
    return 0


if __name__ == "__main__":
    sys.exit(main())
