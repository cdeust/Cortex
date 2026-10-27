#!/usr/bin/env python3
"""Read authenticated, run-bound claude[bot] review evidence for one PR head.

Protocol: the review job of .github/workflows/claude.yml publishes each native
review as a pull request review by claude[bot] on commit_id=<head>, first body
line <!-- claude-review:v2 kind=code|security findings=N run=<run id>-<attempt> -->.
A review is evidence only when the Actions API shows that run is a claude.yml
workflow_run on main with job "review <head>" whose "Validate <kind> review
execution" step succeeded; that step proves the run itself published exactly
this body. Unbound markers (an @claude session, a manual post) are ignored.
Sources: https://docs.github.com/en/rest/pulls/reviews#list-reviews-for-a-pull-request
https://docs.github.com/en/rest/actions/workflow-runs and /workflow-jobs
Self-contained on purpose: pipeline.yml embeds this exact file under python3 -I.
source: ADR-1116
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

Record = dict[str, Any]
BOT = "claude[bot]"
KINDS = ("code", "security")
PREFIX = "<!-- claude-review:"
MARKER = re.compile(
    r"<!-- claude-review:v2 kind=(code|security) findings=(0|[1-9][0-9]*)"
    r" run=([1-9][0-9]*-[1-9][0-9]*) -->"
)
CITED = re.compile(r" run=([1-9][0-9]*-[1-9][0-9]*) -->$")
WORKFLOW = ".github/workflows/claude.yml"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")


class EvidenceError(ValueError):
    """Only fixed diagnostic categories may cross the CLI boundary."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise EvidenceError("arguments")


def _pairs(items: list[tuple[str, Any]]) -> Record:
    value: Record = {}
    for key, item in items:
        if key in value:
            raise EvidenceError("protocol")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise EvidenceError("protocol")


def _json(text: str) -> Any:
    try:
        return json.loads(
            text, object_pairs_hook=_pairs, parse_constant=_invalid_constant
        )
    except (ValueError, RecursionError, TypeError) as exc:
        raise EvidenceError("protocol") from exc


def _api(endpoint: str, *, paginate: bool = False, missing: bool = False) -> Any:
    # https://cli.github.com/manual/gh_api; on HTTP errors the body is on stdout.
    command = ["gh", "api", *(["--paginate", "--slurp"] if paginate else []), endpoint]
    try:
        done = subprocess.run(command, text=True, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        if missing and '"status":"404"' in (exc.stdout or "").replace(" ", ""):
            return None
        raise EvidenceError("api") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError("api") from exc
    return _json(done.stdout)


def _review_job(call: Callable, repo: str, sha: str, token: str) -> Record | None:
    """The trusted job of run <id>-<attempt> that produced a review, else None."""
    run_id, attempt = (int(part) for part in token.split("-"))
    run = call(f"repos/{repo}/actions/runs/{run_id}", missing=True)
    if run is None:
        return None
    if not isinstance(run, dict) or not isinstance(run.get("repository"), dict):
        raise EvidenceError("protocol")
    if (
        run.get("id") != run_id
        or run.get("path") != WORKFLOW
        or run.get("event") != "workflow_run"
        or run.get("head_branch") != "main"
        or str(run["repository"].get("full_name")).casefold() != repo.casefold()
    ):
        return None
    endpoint = f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
    pages = call(endpoint, paginate=True, missing=True)
    if pages is None:
        return None
    if not isinstance(pages, list) or any(
        not isinstance(p, dict) or not isinstance(p.get("jobs"), list) for p in pages
    ):
        raise EvidenceError("protocol")
    jobs = [job for page in pages for job in page["jobs"] if isinstance(job, dict)]
    named = [job for job in jobs if job.get("name") == f"review {sha}"]
    return named[0] if len(named) == 1 else None


def attest(repo: str, sha: str, api: Any = None) -> Callable[[str], Record | None]:
    """Memoised <run id>-<attempt> -> producing job lookup for one PR head."""
    call, cache = (_api if api is None else api), {}

    def job(token: str) -> Record | None:
        if token not in cache:
            cache[token] = _review_job(call, repo, sha, token)
        return cache[token]

    return job


def _pending() -> Record:
    return {"state": "pending", "review_id": 0, "findings": None, "run": ""}


def _shape(review: Any) -> None:
    get = review.get if isinstance(review, dict) else {}.get
    identity, commit = get("id"), get("commit_id")
    if (
        type(identity) is not int
        or identity <= 0
        or not isinstance(get("user"), (dict, type(None)))
        or not isinstance(get("body"), (str, type(None)))
        or not isinstance(get("state"), str)
        or not isinstance(commit, (str, type(None)))
        or (commit is not None and SHA_PATTERN.fullmatch(commit) is None)
    ):
        raise EvidenceError("protocol")


def _bound(review: Record, sha: str, job: Callable) -> tuple[str, Record] | None:
    """(kind, or "" if malformed; producing job) for a run-bound marker, else None."""
    user, body = review.get("user"), review.get("body")
    if (
        not isinstance(user, dict)
        or user.get("login") != BOT
        or user.get("type") != "Bot"
        or not isinstance(body, str)
        or not body.startswith(PREFIX)
        or review.get("commit_id") != sha
    ):
        return None
    first = body.split("\n", 1)[0].rstrip("\r")
    cited = CITED.search(first)
    producer = job(cited.group(1)) if cited else None
    if producer is None:
        return None
    match = MARKER.fullmatch(first)
    valid = match is not None and review["state"] == "COMMENTED"
    return (match.group(1) if valid else ""), producer


def _kind_state(kind: str, items: list[tuple[Record, Record]]) -> Record:
    """One state per kind; a duplicate fails instead of latest-wins."""
    if len(items) != 1:
        return dict(_pending(), state="failed") if items else _pending()
    review, producer = items[0]
    match = MARKER.fullmatch(review["body"].split("\n", 1)[0].rstrip("\r"))
    findings = int(match.group(2))
    state = dict(_pending(), review_id=review["id"], findings=findings)
    state["run"] = match.group(3)
    if producer.get("status") != "completed":
        return state
    name, steps = f"Validate {kind} review execution", producer.get("steps") or []
    steps = [s for s in steps if isinstance(s, dict) and s.get("name") == name]
    if len(steps) != 1 or steps[0].get("conclusion") != "success":
        return dict(state, state="failed")
    return dict(state, state="unresolved" if findings else "success")


def review_evidence(reviews: Any, expected_sha: str, job: Callable) -> Record:
    """Classify this head's run-bound claude[bot] reviews; the rest stay pending."""
    valid = isinstance(expected_sha, str) and SHA_PATTERN.fullmatch(expected_sha)
    result: Record = {kind: _pending() for kind in KINDS}
    result.update(state="pending", reason="review_missing", reviews_complete=False)
    result["sha"] = expected_sha if valid else ""
    try:
        if not valid:
            raise EvidenceError("arguments")
        if not isinstance(reviews, list):
            raise EvidenceError("protocol")
        for review in reviews:
            _shape(review)
        found: dict[str, list] = {kind: [] for kind in (*KINDS, "")}
        for review in reviews:
            hit = _bound(review, expected_sha, job)
            if hit:
                found[hit[0]].append((review, hit[1]))
        result.update({kind: _kind_state(kind, found[kind]) for kind in KINDS})
        values = [result[kind]["state"] for kind in KINDS]
        values += ["failed"] if found[""] else []
        result["reviews_complete"] = all(v in ("success", "unresolved") for v in values)
        if "failed" in values or "unresolved" in values:
            reason = "review_failed" if "failed" in values else "review_unresolved"
            result.update(state="blocked", reason=reason)
        elif "pending" in values:
            bound = any(found.values())
            result["reason"] = "review_pending" if bound else "review_missing"
        else:
            result.update(state="success", reason="reviews_complete")
    except EvidenceError as exc:
        result.update(state="blocked", reason=str(exc), reviews_complete=False)
    return result


def _eligible(pull: Any, repo: str, sha: str) -> None:
    """Open, non-draft, same-repository PR to main whose live head is sha."""
    get = pull.get if isinstance(pull, dict) else {}.get
    parts = (get("head"), get("base"))
    if any(
        not isinstance(part, dict)
        or not isinstance(part.get("repo"), dict)
        or not isinstance(part["repo"].get("full_name"), str)
        for part in parts
    ):
        raise EvidenceError("pr_eligibility")
    head, base = parts
    repos = (head["repo"], base["repo"])
    if (
        pull.get("state") != "open"
        or pull.get("draft") is not False
        or base.get("ref") != "main"
        or any(item["full_name"].casefold() != repo.casefold() for item in repos)
    ):
        raise EvidenceError("pr_eligibility")
    if head.get("sha") != sha:
        raise EvidenceError("head_moved")


def _fetch(args: argparse.Namespace) -> Record:
    endpoint = f"repos/{args.repo}/pulls/{args.pr}"
    _eligible(_api(endpoint), args.repo, args.sha)
    pages = _api(f"{endpoint}/reviews", paginate=True)
    if not isinstance(pages, list) or any(not isinstance(p, list) for p in pages):
        raise EvidenceError("protocol")
    reviews = [review for page in pages for review in page]
    result = review_evidence(reviews, args.sha, attest(args.repo, args.sha))
    _eligible(_api(endpoint), args.repo, args.sha)
    return result


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = Parser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--sha", required=True)
    for flag in ("--github-output", "--require-complete", "--allow-pending"):
        parser.add_argument(flag, action="store_true")
    args = parser.parse_args(argv)
    if (
        REPO_PATTERN.fullmatch(args.repo) is None
        or args.repo.split("/")[1] in (".", "..")
        or args.pr <= 0
        or SHA_PATTERN.fullmatch(args.sha) is None
    ):
        raise EvidenceError("arguments")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = _arguments(argv)
        result = _fetch(args)
        if args.github_output:
            # An unset GITHUB_OUTPUT opens Path("."), a directory: OSError.
            with Path(os.environ.get("GITHUB_OUTPUT", "")).open("a") as output:
                output.write(f"state={result['state']}\nsha={result['sha']}\n")
        print(json.dumps(result, sort_keys=True))
        if args.allow_pending and result["state"] == "pending":
            return 0
        # Complete means success or unresolved findings, never failed or pending.
        if args.require_complete and result["reviews_complete"]:
            return 0
        return {"success": 0, "pending": 2, "blocked": 1}[result["state"]]
    except OSError:
        print("claude reviews: output", file=sys.stderr)
        return 1
    except EvidenceError as exc:
        print(f"claude reviews: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
