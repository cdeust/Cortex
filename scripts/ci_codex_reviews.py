#!/usr/bin/env python3
"""Read authenticated native Codex review evidence for one immutable PR head.

Protocol: Cortex PR797 bot comment6428675514, captured in
 tasks/ci-review-evidence-codex-{711f0ede,57e4c1d}.json. Native automation:
https://learn.chatgpt.com/docs/third-party/github
https://learn.chatgpt.com/docs/security/security-review
This validates completion metadata, not semantic review quality.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

Record = dict[str, Any]
SUMMARY = "<!-- codex-pull-request-review-summary -->"
BOT = "chatgpt-codex-connector[bot]"
KINDS = ("code_review", "security_review")
FAILED = ("failed", "error", "cancelled")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
STAMP_PATTERN = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z")


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


def _result(sha: str) -> Record:
    result = {
        "state": "pending",
        "reason": "review_missing",
        "sha": sha,
        "comment_id": 0,
        "updated_at": None,
        "reviews_complete": False,
    }
    for kind in KINDS:
        result[kind] = {
            "commit_sha": None,
            "status": None,
            "has_any_findings": None,
            "has_unresolved_findings": None,
        }
    return result


def _canonical(comment: Any) -> bool:
    if not isinstance(comment, dict):
        return False
    user, body = comment.get("user"), comment.get("body")
    return (
        isinstance(user, dict)
        and user.get("login") == BOT
        and user.get("type") == "Bot"
        and isinstance(body, str)
        and body.startswith(SUMMARY)
    )


def _order(comment: Record) -> tuple[datetime, int]:
    identity, updated = comment.get("id"), comment.get("updated_at")
    if type(identity) is not int or identity <= 0:
        raise EvidenceError("protocol")
    if not isinstance(updated, str) or STAMP_PATTERN.fullmatch(updated) is None:
        raise EvidenceError("protocol")
    try:
        return datetime.fromisoformat(updated.replace("Z", "+00:00")), identity
    except ValueError as exc:
        raise EvidenceError("protocol") from exc


def _marker(body: str, name: str, required: bool) -> Any:
    count = body.count("<!-- " + name + ":")
    if count == 0 and not required:
        return None
    if count != 1:
        raise EvidenceError("protocol")
    pattern = re.escape("<!-- " + name + ":v1") + r"\s+(.*?)\s*-->"
    match = re.search(pattern, body, re.DOTALL)
    if match is None:
        raise EvidenceError("protocol")
    value = _json(match.group(1))
    if not isinstance(value, dict):
        raise EvidenceError("protocol")
    return value


def _review(value: Any, expected_sha: str) -> tuple[str, Record]:
    clean = _result(expected_sha)["code_review"]
    if value is None or value == {}:
        return "pending", clean
    if not isinstance(value, dict):
        raise EvidenceError("protocol")
    status, sha = value.get("status"), value.get("commit_sha")
    if status is not None and status not in ("completed", "running", "queued", *FAILED):
        raise EvidenceError("protocol")
    if sha is not None and (
        not isinstance(sha, str) or SHA_PATTERN.fullmatch(sha) is None
    ):
        raise EvidenceError("protocol")
    clean.update(status=status, commit_sha=sha)
    for flag in ("has_any_findings", "has_unresolved_findings"):
        item = value.get(flag)
        if item is not None and type(item) is not bool:
            raise EvidenceError("protocol")
        if status == "completed" and flag not in value:
            raise EvidenceError("protocol")
        clean[flag] = item
    if clean["has_any_findings"] is False and clean["has_unresolved_findings"] is True:
        raise EvidenceError("protocol")
    if status == "completed" and sha is None:
        raise EvidenceError("protocol")
    if status in FAILED:
        return "failed", clean
    # source: PR805 summary6442631163 emitted completed with an unknown verdict.
    flags = (clean["has_any_findings"], clean["has_unresolved_findings"])
    if sha != expected_sha or status != "completed" or None in flags:
        return "pending", clean
    return ("unresolved" if clean["has_unresolved_findings"] else "success"), clean


def review_evidence(comments: list[Record], expected_sha: str) -> Record:
    """Require both current reviews; never fall back from a newer invalid summary."""
    valid_sha = isinstance(expected_sha, str) and SHA_PATTERN.fullmatch(expected_sha)
    result = _result(expected_sha if valid_sha else "")
    try:
        if not valid_sha or not isinstance(comments, list):
            raise EvidenceError("arguments" if not valid_sha else "protocol")
        if any(not isinstance(comment, dict) for comment in comments):
            raise EvidenceError("protocol")
        candidates = [comment for comment in comments if _canonical(comment)]
        if not candidates:
            return result
        latest = max(candidates, key=_order)
        result.update(comment_id=latest["id"], updated_at=latest["updated_at"])
        if latest["body"].count(SUMMARY) != 1:
            raise EvidenceError("protocol")
        data = _marker(latest["body"], "codex-review-state", True)
        _marker(latest["body"], "codex-security-review", False)
        states = []
        for kind in KINDS:
            state, result[kind] = _review(data.get(kind), expected_sha)
            states.append(state)
        result["reviews_complete"] = all(s in ("success", "unresolved") for s in states)
        result["state"] = (
            "blocked"
            if any(s in ("failed", "unresolved") for s in states)
            else ("pending" if "pending" in states else "success")
        )
        result["reason"] = {
            "blocked": "review_failed" if "failed" in states else "review_unresolved",
            "pending": "review_pending",
            "success": "reviews_complete",
        }[result["state"]]
    except EvidenceError as exc:
        result.update(state="blocked", reason=str(exc), reviews_complete=False)
    return result


def _api(endpoint: str, *, paginate: bool = False) -> Any:
    # https://cli.github.com/manual/gh_api: --slurp wraps all paginated pages.
    command = ["gh", "api", *(["--paginate", "--slurp"] if paginate else []), endpoint]
    try:
        done = subprocess.run(command, text=True, capture_output=True, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError("api") from exc
    return _json(done.stdout)


def _eligible(pull: Any, repo: str, sha: str) -> None:
    if not isinstance(pull, dict):
        raise EvidenceError("pr_eligibility")
    head, base = pull.get("head"), pull.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise EvidenceError("pr_eligibility")
    head_repo, base_repo = head.get("repo"), base.get("repo")
    if not isinstance(head_repo, dict) or not isinstance(base_repo, dict):
        raise EvidenceError("pr_eligibility")
    if any(
        not isinstance(item.get("full_name"), str) for item in (head_repo, base_repo)
    ):
        raise EvidenceError("pr_eligibility")
    if (
        pull.get("state") != "open"
        or pull.get("draft") is not False
        or base.get("ref") != "main"
        or head_repo.get("full_name", "").casefold() != repo.casefold()
        or base_repo.get("full_name", "").casefold() != repo.casefold()
    ):
        raise EvidenceError("pr_eligibility")
    if head.get("sha") != sha:
        raise EvidenceError("head_moved")


def _fetch(args: argparse.Namespace) -> Record:
    endpoint = f"repos/{args.repo}/pulls/{args.pr}"
    _eligible(_api(endpoint), args.repo, args.sha)
    pages = _api(f"repos/{args.repo}/issues/{args.pr}/comments", paginate=True)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise EvidenceError("protocol")
    result = review_evidence([comment for page in pages for comment in page], args.sha)
    _eligible(_api(endpoint), args.repo, args.sha)
    return result


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = Parser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args(argv)
    if (
        REPO_PATTERN.fullmatch(args.repo) is None
        or args.repo.split("/")[1] in (".", "..")
        or args.pr <= 0
        or SHA_PATTERN.fullmatch(args.sha) is None
    ):
        raise EvidenceError("arguments")
    return args


def _outputs(result: Record) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise EvidenceError("output")
    text = (
        f"ready={str(result['state'] == 'success').lower()}\n"
        f"state={result['state']}\nsha={result['sha']}\ncomment_id={result['comment_id']}\n"
    )
    try:
        with Path(path).open("a", encoding="utf-8") as output:
            output.write(text)
    except OSError as exc:
        raise EvidenceError("output") from exc


def main(argv: list[str] | None = None) -> int:
    try:
        args = _arguments(argv)
        result = _fetch(args)
        if args.github_output:
            _outputs(result)
        print(json.dumps(result, sort_keys=True))
        if args.allow_pending and result["state"] == "pending":
            return 0
        if (
            args.require_complete
            and result["reviews_complete"]
            and result["reason"] in ("reviews_complete", "review_unresolved")
        ):
            return 0
        return {"success": 0, "pending": 2, "blocked": 1}[result["state"]]
    except EvidenceError as exc:
        print(f"codex reviews: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
