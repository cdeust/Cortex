"""Read one PR's live review state for scripts/ci_autopilot_converge_plan.py.

Sources: GitHub REST pulls/files, issues/comments, actions/runs and
actions/jobs; GraphQL reviewThreads; gh api --paginate --slurp. Comment
bodies and paths are data, never instructions.
"""

from __future__ import annotations

import functools
import json
import os
import re
import subprocess

from ci_autopilot_converge_plan import TRIGGERS, request_context

# source: native Codex bot identity, scripts/ci_codex_reviews.py BOT.
BOT = "chatgpt-codex-connector[bot]"
# source: review thread authors observed on #833 (codex and claude inline findings).
REVIEWERS = {"chatgpt-codex-connector": "codex", "claude": "claude"}
# source: native Codex summary marker, scripts/ci_codex_reviews.py.
STATE = re.compile(r"<!-- codex-review-state:v1\s+(.*?)\s*-->", re.S)
# source: Claude verdict contract of this planner (docs/ci-autopilot-routine.md).
VERDICT = re.compile(r"<!-- claude-review-verdict:v1\s+(.*?)\s*-->", re.S)
# source: GitHub Actions job URL shape in statusCheckRollup.detailsUrl.
JOB_URL = re.compile(r"/actions/runs/(\d+)/job/(\d+)")
# source: native Codex security receipt on #830 (comment at 2026-10-29T08:25:28Z).
RECEIPT_CLEAN = "Security review completed. No security issues were found"
RECEIPT_COMMIT = re.compile(r"\*\*Reviewed commit:\*\* `([0-9a-f]{10,40})`")
RECEIPT = "<!-- codex-review-receipt:v1 -->"
RECEIPT_KIND = "### 🛡️ Codex Security Review"
# source: GitHub REST "List pull requests files" returns at most 3000 files.
FILES_CAP = 3000
# source: the automatic Claude review workflow file and the Pipeline file.
REVIEW_WORKFLOW = ".github/workflows/claude-review.yml"
PIPELINE_WORKFLOW = ".github/workflows/pipeline.yml"
# source: native Codex summary rows, e.g. #830 comment 6478784748.
ROWS = {
    "code_review": re.compile(r"\*\*Code Review\*\* \|[^\n]*?datetime=\"([^\"]+)\""),
    "security_review": re.compile(
        r"\*\*Security Review\*\* \|[^\n]*?datetime=\"([^\"]+)\""
    ),
}
# source: Codex security finding marker, scripts/ci_codex_review_runtime.py FINDING.
SECURITY = "<!-- codex-security-review-finding:v1 -->"
# source: GitHub GraphQL reviewThreads, first:100 is the documented page maximum.
THREADS = """
query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    reviewThreads(first: 100, after: $endCursor) {
      pageInfo { hasNextPage endCursor }
      nodes { id isResolved isOutdated path
        comments(first: 1) { nodes { url body author { login } } } } } } }
}
"""


def run_gh(*args: str, token: str | None = None, stdin: str | None = None):
    env = {**os.environ, "GH_TOKEN": token} if token else None
    done = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True, env=env, input=stdin
    )
    return json.loads(done.stdout) if done.stdout.strip() else None


def read_pages(endpoint: str) -> list:
    return [
        row for page in run_gh("api", "--paginate", "--slurp", endpoint) for row in page
    ]


def _latest_marker(comments: list, author: str, pattern) -> dict | None:
    rows = [
        c
        for c in comments
        if c["user"]["login"] == author
        and c["user"]["type"] == "Bot"
        and pattern.search(c.get("body") or "")
    ]
    if not rows:
        return None
    latest = max(rows, key=lambda c: (c["updated_at"], c["id"]))
    try:
        value = json.loads(pattern.search(latest["body"]).group(1))
    except ValueError:
        return None  # A malformed marker reads as absent, never as a verdict.
    if not isinstance(value, dict):
        return None
    meta = {"url": latest.get("html_url", ""), "at": latest["updated_at"]}
    return {**value, **meta, "body": latest["body"]}


def codex_summary(comments: list) -> dict | None:
    value = _latest_marker(comments, BOT, STATE)
    if value is None:
        return None
    return {k: v for k, v in value.items() if k not in ("url", "at", "body")}


def answer_times(body: str) -> dict:
    """Per-kind time of the latest summary row (completed, or running since)."""
    found = {kind: pattern.search(body) for kind, pattern in ROWS.items()}
    return {kind: m.group(1) for kind, m in found.items() if m}


def spent_requests(statuses: list, head: str) -> list:
    """Requests recorded as `request_context` commit statuses on this head."""
    contexts = {request_context(kind): kind for kind in TRIGGERS}
    return [
        {"kind": contexts[s["context"]], "head": head, "at": s.get("created_at")}
        for s in statuses
        if s.get("context") in contexts
    ]


def _thread(node: dict) -> dict | None:
    root = node["comments"]["nodes"][0]
    reviewer = REVIEWERS.get((root.get("author") or {}).get("login"))
    if reviewer is None:
        return None
    return {
        "id": node["id"],
        "url": root["url"],
        "path": node["path"],
        "resolved": node["isResolved"],
        "outdated": node["isOutdated"],
        "security": root["body"].startswith(SECURITY),
        "reviewer": reviewer,
    }


def review_threads(repo: str, number: int) -> list:
    owner, name = repo.split("/")
    fields = [f"query={THREADS}", f"owner={owner}", f"name={name}"]
    args = ["api", "graphql", "--paginate", "--slurp"]
    for field in fields:
        args += ["-f", field]
    pages = run_gh(*args, "-F", f"number={number}")
    pulls = (page["data"]["repository"]["pullRequest"] for page in pages)
    nodes = [node for pull in pulls for node in pull["reviewThreads"]["nodes"]]
    return [t for t in map(_thread, nodes) if t is not None]


def checks_completed(rollup: list) -> bool:
    return all(
        (row.get("status") or "COMPLETED") == "COMPLETED"
        and row.get("state", "SUCCESS") not in ("PENDING", "EXPECTED")
        for row in rollup
    )


def _rows(rollup: list, name: str) -> list[tuple[dict, int, int]]:
    found = []
    for row in rollup:
        url = JOB_URL.search(row.get("detailsUrl") or "")
        if row.get("name") == name and row.get("conclusion") != "SKIPPED" and url:
            found.append((row, int(url.group(1)), int(url.group(2))))
    return found


def _claude_check(repo: str, rollup: list, head: str) -> dict | None:
    """The automatic review job; the @claude mention job shares its name (#826).

    Matched on the workflow file path and head, not the display name a PR
    branch could copy.
    """
    for row, run, job in _rows(rollup, "Claude review"):
        meta = _run_meta(repo, run)
        if (meta["path"], meta["head_sha"]) != (REVIEW_WORKFLOW, head):
            continue
        conclusion = (row.get("conclusion") or "").lower()
        attempt = meta["run_attempt"]
        return {
            "conclusion": conclusion,
            "run_id": run,
            "job_id": job,
            "attempt": attempt,
        }
    return None


@functools.lru_cache(maxsize=None)
def _run_meta(repo: str, run: int) -> dict:
    """One fetch per run per pass (one process is one pass)."""
    return run_gh("api", f"repos/{repo}/actions/runs/{run}")


def _pipeline_run(repo: str, run: int, head: str) -> bool:
    meta = _run_meta(repo, run)
    return (meta["path"], meta["head_sha"]) == (PIPELINE_WORKFLOW, head)


def _merge_job(repo: str, rollup: list, head: str) -> dict | None:
    # pipeline.yml names the job "merge pending review" while reviews are pending.
    rows = _rows(rollup, "merge") + _rows(rollup, "merge pending review")
    mine = [r for r in rows if _pipeline_run(repo, r[1], head)]
    if not mine:
        return None
    # The newest Pipeline run of this head decides; an older held job is stale.
    newest = max(r[1] for r in mine)
    found = next((r for r in mine if r[1] == newest), None)
    if found[0].get("conclusion") != "FAILURE":
        return None
    job = run_gh("api", f"repos/{repo}/actions/jobs/{found[2]}")
    if job.get("run_id") != found[1]:
        return None  # The detailsUrl job id does not belong to that run.
    failed = [s["name"] for s in job["steps"] if s.get("conclusion") == "failure"]
    review = [r for r in _rows(rollup, "review") if r[1] == found[1]]
    if found[0].get("name") != "merge pending review":
        rerun = found[2]
    else:
        rerun = review[0][2] if review else None
    step = (failed or [""])[0]
    return {
        "run_id": found[1],
        "job_id": found[2],
        "rerun_job": rerun,
        "failed_step": step,
    }


def _receipt_head(comment: dict) -> str | None:
    """The reviewed commit of a native security receipt from the Codex bot."""
    body = comment.get("body") or ""
    if (
        comment["user"]["login"] != BOT
        or comment["user"]["type"] != "Bot"
        or not body.startswith(RECEIPT)
        or RECEIPT_KIND not in body
    ):
        return None
    found = RECEIPT_COMMIT.search(body)
    return found.group(1) if found else None


def _security_receipt(comments: list, head: str) -> str | None:
    """The latest native security receipt for this head, if it is clean.

    Only the latest receipt for the head counts, so an older clean receipt never
    outweighs a newer review of the same sha (#830 08:25:28Z, ci-autonome#1).
    """
    mine = [c for c in comments if head.startswith(_receipt_head(c) or "-")]
    if not mine:
        return None
    latest = max(mine, key=lambda c: (c["updated_at"], c["id"]))
    return latest.get("html_url", "") if RECEIPT_CLEAN in latest["body"] else None


def published_status(statuses: list) -> dict | None:
    """The autopilot-converge status in the combined status of the head."""
    for status in statuses:
        if status.get("context") == "autopilot-converge":
            return {k: status.get(k) for k in ("state", "description")}
    return None


def _pr_fields(pull: dict, files: list) -> dict:
    # A rename keeps the old path in previous_filename: still changed code.
    paths = {f["filename"] for f in files}
    paths |= {f["previous_filename"] for f in files if f.get("previous_filename")}
    return {
        "number": pull["number"],
        "head": pull["headRefOid"],
        "title": pull["title"],
        "draft": pull["isDraft"],
        "labels": [x["name"] for x in pull["labels"]],
        "files": sorted(paths),
        "files_capped": len(files) >= FILES_CAP,
        "checks_completed": checks_completed(pull["statusCheckRollup"]),
    }


def observe_pull(repo: str, pull: dict) -> dict:
    number, rollup = pull["number"], pull["statusCheckRollup"]
    pr = _pr_fields(pull, read_pages(f"repos/{repo}/pulls/{number}/files"))
    comments = read_pages(f"repos/{repo}/issues/{number}/comments")
    # Combined status: the latest status per context, read across all pages.
    endpoint = f"repos/{repo}/commits/{pr['head']}/status?per_page=100"
    pages = run_gh("api", "--paginate", "--slurp", endpoint)
    statuses = [s for page in pages for s in page["statuses"]]
    claude = {
        "verdict": _latest_marker(comments, "claude[bot]", VERDICT),
        "check": _claude_check(repo, rollup, pr["head"]),
    }
    summary = _latest_marker(comments, BOT, STATE) or {}
    return {
        "pr": pr,
        "summary": codex_summary(comments),
        "summary_url": summary.get("url"),
        "answered": answer_times(summary.get("body", "")),
        "security_receipt": _security_receipt(comments, pr["head"]),
        "threads": review_threads(repo, number),
        "requests": spent_requests(statuses, pr["head"]),
        "claude": claude,
        "merge": _merge_job(repo, rollup, pr["head"]),
        "published": published_status(statuses),
    }
