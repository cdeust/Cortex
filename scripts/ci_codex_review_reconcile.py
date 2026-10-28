#!/usr/bin/env python3
"""Reconcile native review gates through the existing authenticated coordinator.

Sources: GitHub's supported schedule/workflow_dispatch events and paginated PR API.
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
https://docs.github.com/en/rest/pulls/pulls#list-pull-requests
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_codex_review_event as events  # noqa: E402
from ci_codex_review_resume import PREREQUISITES, _success  # noqa: E402
from ci_codex_reviews import EvidenceError, REPO_PATTERN, SHA_PATTERN  # noqa: E402


def _diagnostic(number, category):
    identity = str(number) if type(number) is int else "unknown"
    print(f"codex reconcile: pr={identity} {category}", file=sys.stderr)


def _rows(pages):
    if (
        not isinstance(pages, list)
        or not pages
        or any(not isinstance(page, list) for page in pages)
    ):
        raise EvidenceError("protocol")
    unique, rejected = {}, set()
    for row in (item for page in pages for item in page):
        try:
            number = events.source.positive(row.get("number"))
        except (AttributeError, EvidenceError):
            _diagnostic(None, "protocol")
            continue
        if number in unique or number in rejected:
            unique.pop(number, None)
            rejected.add(number)
            _diagnostic(number, "protocol")
        else:
            unique[number] = row
    return unique.values()


def _candidate(repo, row):
    number = events.source.positive(row["number"])
    if row.get("state") != "open" or row.get("draft") is not False:
        return None
    head = row.get("head")
    if not isinstance(head, dict):
        raise EvidenceError("protocol")
    repository = head.get("repo")
    if not isinstance(repository, dict) or not isinstance(
        repository.get("full_name"), str
    ):
        return None
    if repository["full_name"].casefold() != repo.casefold():
        return None
    sha = head.get("sha")
    if not isinstance(sha, str) or SHA_PATTERN.fullmatch(sha) is None:
        raise EvidenceError("protocol")
    if events.source.live_pr(repo, number, sha) is None:
        return None
    run = events.source.latest(repo, sha, number)
    if run is None:
        return None
    jobs = events._jobs(repo, run)
    indexed = {job["name"]: job for job in jobs}
    if any(job["status"] != "completed" for job in jobs) or not all(
        _success(indexed.get(name, {})) for name in PREREQUISITES
    ):
        return None
    proof = events._proof(repo, number, run, jobs)
    if proof.get("reason") == "api":
        raise EvidenceError("api")
    plan = events._plan(run, jobs, proof, sha)
    return {"number": number, "sha": sha} if plan["action"] != "none" else None


def discover(repo):
    # per_page=100 is the documented REST maximum; gh follows every Link page.
    pages = events.source._api(
        f"repos/{repo}/pulls?state=open&per_page=100", paginate=True
    )
    selected = []
    for row in _rows(pages):
        try:
            candidate = _candidate(repo, row)
        except OSError:
            _diagnostic(row["number"], "api")
            continue
        except EvidenceError as exc:
            _diagnostic(row["number"], "api" if str(exc) == "api" else "protocol")
            continue
        if candidate is not None:
            selected.append(candidate)
    return selected


def _trigger(flags):
    try:
        pr_flag, number, sha_flag, sha = flags
    except ValueError as exc:
        raise EvidenceError("arguments") from exc
    if (pr_flag, sha_flag) != ("--pr", "--sha"):
        raise EvidenceError("arguments")
    if not number.isascii() or not number.isdecimal() or number.startswith("0"):
        raise EvidenceError("arguments")
    if SHA_PATTERN.fullmatch(sha) is None:
        raise EvidenceError("arguments")
    try:
        number = events.source.positive(int(number))
    except ValueError as exc:
        raise EvidenceError("arguments") from exc
    return {"number": number, "sha": sha, "run_id": None}


def main(argv=None):
    try:
        flags = sys.argv[1:] if argv is None else argv
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if REPO_PATTERN.fullmatch(repo) is None or repo.split("/")[1] in (".", ".."):
            raise EvidenceError("environment")
        if not os.environ.get("GH_TOKEN"):
            raise EvidenceError("environment")
        if flags == ["--list"]:
            result = discover(repo)
            path = os.environ.get("GITHUB_OUTPUT")
            if not path:
                raise EvidenceError("output")
            with Path(path).open("a", encoding="utf-8") as output:
                output.write("prs=" + json.dumps(result) + "\n")
        else:
            result = events.resume(repo, _trigger(flags))
        print(json.dumps(result, sort_keys=True))
        return 0
    except OSError:
        print("codex reconcile: api", file=sys.stderr)
        return 1
    except EvidenceError as exc:
        print(f"codex reconcile: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
