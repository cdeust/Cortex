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
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# CLI callers execute this trusted file; the isolated workflow preloads its
# exact embedded runtime, so candidate checkout imports are never consulted.
if "ci_codex_review_runtime" not in sys.modules:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_codex_review_runtime as runtime  # noqa: E402
from ci_codex_review_runtime import _outputs  # noqa: E402
from ci_codex_review_comments import _authenticate_editor, _bot_author, _canonical  # noqa: E402
from ci_codex_review_comments import BLOCKED_REASONS, BLOCKING, security_receipt  # noqa: E402

Record = dict[str, Any]
SUMMARY = "<!-- codex-pull-request-review-summary -->"
BOT = "chatgpt-codex-connector[bot]"
KINDS = ("code_review", "security_review")
FAILED = ("failed", "error", "cancelled")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
STAMP_PATTERN = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z")


class EvidenceError(runtime.EvidenceError):
    """Preserve the evidence-reader exception interface for its event callers."""


class APIError(runtime.APIError, EvidenceError):
    """Retain transport category within the reader exception catch boundary."""


def _json(text: str) -> Any:
    try:
        return runtime._json(text)
    except runtime.EvidenceError as exc:
        raise EvidenceError(str(exc)) from exc


def _api(endpoint: str, *, paginate: bool = False, fields: Record | None = None) -> Any:
    try:
        options = {"fields": fields} if fields is not None else {}
        return runtime._api(endpoint, paginate=paginate, **options)
    except runtime.APIError as exc:
        raise APIError(exc.category) from exc
    except runtime.EvidenceError as exc:
        raise EvidenceError(str(exc)) from exc


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise EvidenceError("arguments")


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


def _reviews(latest, target, comments):
    expected_sha, repo, pr = target
    reviews = {}
    data = _marker(latest["body"], "codex-review-state", True)
    security = _marker(latest["body"], "codex-security-review", False)
    states = []
    for kind in KINDS:
        state, reviews[kind] = _review(data.get(kind), expected_sha)
        proof = None
        if kind == "security_review" and state == "pending" and repo and pr:
            proof = runtime.resolve_security(
                (repo, pr, expected_sha), latest["body"], reviews[kind], security
            ) or security_receipt(
                comments, (repo, pr, expected_sha), reviews[kind], security
            )
        if proof is not None:
            state = proof.pop("state")
            reviews[kind]["resolution"] = proof
        states.append(state)
    return states, reviews


def review_evidence(
    comments: list[Record], expected_sha: str, repo=None, pr=None
) -> Record:
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
        latest_order = _order(latest)
        # A human can remove the marker while retaining the original Bot author.
        for item in comments:
            if _bot_author(item) and _order(item) >= latest_order:
                _authenticate_editor(item)
        if latest["body"].count(SUMMARY) != 1:
            raise EvidenceError("protocol")
        states, details = _reviews(latest, (expected_sha, repo, pr), comments)
        result.update(details)
        result["reviews_complete"] = all(s in ("success", "unresolved") for s in states)
        result["state"] = (
            "blocked"
            if any(s in BLOCKING for s in states)
            else ("pending" if "pending" in states else "success")
        )
        result["reason"] = {
            "blocked": next((r for s, r in BLOCKED_REASONS if s in states), "review_unresolved"),
            "pending": "review_pending",
            "success": "reviews_complete",
        }[result["state"]]
    except runtime.EvidenceError as exc:
        result.update(state="blocked", reason=str(exc), reviews_complete=False)
        if isinstance(exc, runtime.APIError):
            result["api_category"] = exc.category
    return result


def summary_comments(repo: str, pr: int, sha: str, request) -> list[Record]:
    try:
        return runtime.summary_comments(repo, pr, sha, request)
    except runtime.APIError as exc:
        raise APIError(exc.category) from exc
    except runtime.EvidenceError as exc:
        raise EvidenceError(str(exc)) from exc


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
    comments = summary_comments(args.repo, args.pr, args.sha, _api)
    result = review_evidence(comments, args.sha, args.repo, args.pr)
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
    except runtime.EvidenceError as exc:
        print(f"codex reviews: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
