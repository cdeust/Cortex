#!/usr/bin/env python3
"""Read authenticated claude[bot] review evidence for one immutable PR head.

Protocol: the review job of .github/workflows/claude.yml publishes each native
review as a pull request review by claude[bot] on commit_id=<head>; its first
body line is <!-- claude-review:v1 kind=code|security findings=N -->.
Activation is read from main, never from the PR: main's claude.yml must declare
CLAUDE_REVIEW_GATE: required, otherwise the state is not_required (Codex-only).
Sources: https://docs.github.com/en/rest/pulls/reviews#list-reviews-for-a-pull-request
https://docs.github.com/en/rest/repos/contents#get-repository-content
Self-contained on purpose: pipeline.yml embeds this exact file under python3 -I.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

Record = dict[str, Any]
BOT = "claude[bot]"
KINDS = ("code", "security")
PREFIX = "<!-- claude-review:"
MARKER = re.compile(
    r"<!-- claude-review:v1 kind=(code|security) findings=(0|[1-9][0-9]*) -->"
)
GATE = re.compile(r"  CLAUDE_REVIEW_GATE: (\S+)")
WORKFLOWS = ".github/workflows"
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


def gate_mode(text: str) -> bool:
    """True only when the workflow text declares the review gate required."""
    values = [m.group(1) for m in map(GATE.fullmatch, text.splitlines()) if m]
    if len(values) > 1 or any(value not in ("observe", "required") for value in values):
        raise EvidenceError("protocol")
    return values == ["required"]


def read_gate(repo: str, api: Any = None) -> bool:
    """Read main's claude.yml; the listing makes absence an answer, not an error."""
    call = _api if api is None else api
    listing = call(f"repos/{repo}/contents/{WORKFLOWS}?ref=main")
    if not isinstance(listing, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
        for entry in listing
    ):
        raise EvidenceError("protocol")
    entries = [entry for entry in listing if entry["name"] == "claude.yml"]
    if not entries:
        return False
    if len(entries) != 1 or entries[0].get("type") != "file":
        raise EvidenceError("protocol")
    record = call(f"repos/{repo}/contents/{WORKFLOWS}/claude.yml?ref=main")
    if (
        not isinstance(record, dict)
        or record.get("encoding") != "base64"
        or not isinstance(record.get("content"), str)
    ):
        raise EvidenceError("protocol")
    try:
        raw = base64.b64decode("".join(record["content"].split()), validate=True)
        return gate_mode(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise EvidenceError("protocol") from exc


def _result(sha: str, required: bool) -> Record:
    state = "pending" if required else "not_required"
    reason = "review_missing" if required else "not_required"
    pending = {"state": "pending", "review_id": 0, "findings": None}
    kinds = {kind: dict(pending) for kind in KINDS}
    return dict(kinds, state=state, reason=reason, sha=sha, required=required) | {
        "reviews_complete": False
    }


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


def _authentic(review: Record) -> bool:
    user, body = review.get("user"), review.get("body")
    return (
        isinstance(user, dict)
        and user.get("login") == BOT
        and user.get("type") == "Bot"
        and isinstance(body, str)
        and body.startswith(PREFIX)
    )


def _classify(current: list[Record]) -> tuple[dict[str, Record], bool]:
    """One state per kind; a duplicate kind fails instead of latest-wins."""
    found: dict[str, list[tuple[int, int]]] = {kind: [] for kind in KINDS}
    malformed = False
    for review in current:
        match = MARKER.fullmatch(review["body"].split("\n", 1)[0].rstrip("\r"))
        if match is None or review["state"] != "COMMENTED":
            malformed = True
            continue
        found[match.group(1)].append((review["id"], int(match.group(2))))
    states = {}
    for kind, items in found.items():
        state, identity, findings = "pending", 0, None
        if len(items) > 1:
            state = "failed"
        elif items:
            identity, findings = items[0]
            state = "unresolved" if findings else "success"
        states[kind] = {"state": state, "review_id": identity, "findings": findings}
    return states, malformed


def review_evidence(reviews: Any, expected_sha: str, required: Any = True) -> Record:
    """Classify this head's claude[bot] marker reviews; stale heads stay pending."""
    valid = isinstance(expected_sha, str) and SHA_PATTERN.fullmatch(expected_sha)
    result = _result(expected_sha if valid else "", required is True)
    try:
        if not valid or type(required) is not bool:
            raise EvidenceError("arguments")
        if not required:
            return result
        if not isinstance(reviews, list):
            raise EvidenceError("protocol")
        for review in reviews:
            _shape(review)
        current = [
            r for r in reviews if _authentic(r) and r.get("commit_id") == expected_sha
        ]
        states, malformed = _classify(current)
        result.update(states)
        values = [item["state"] for item in states.values()]
        values += ["failed"] if malformed else []
        result["reviews_complete"] = all(v in ("success", "unresolved") for v in values)
        if "failed" in values or "unresolved" in values:
            reason = "review_failed" if "failed" in values else "review_unresolved"
            result.update(state="blocked", reason=reason)
        elif "pending" in values:
            result["reason"] = "review_pending" if current else "review_missing"
        else:
            result.update(state="success", reason="reviews_complete")
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
    required = True if args.assume_required else read_gate(args.repo)
    reviews: list[Any] = []
    if required:
        pages = _api(f"{endpoint}/reviews", paginate=True)
        if not isinstance(pages, list) or any(not isinstance(p, list) for p in pages):
            raise EvidenceError("protocol")
        reviews = [review for page in pages for review in page]
    result = review_evidence(reviews, args.sha, required)
    _eligible(_api(endpoint), args.repo, args.sha)
    return result


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = Parser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--sha", required=True)
    for flag in ("--github-output", "--require-complete", "--allow-pending"):
        parser.add_argument(flag, action="store_true")
    # claude.yml's verify job only: prove publication even in observe mode.
    parser.add_argument("--assume-required", action="store_true")
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
    required = str(result["required"]).lower()
    text = f"state={result['state']}\nsha={result['sha']}\nrequired={required}\n"
    try:
        # An unset GITHUB_OUTPUT opens Path("."), a directory: OSError, output.
        with Path(os.environ.get("GITHUB_OUTPUT", "")).open(
            "a", encoding="utf-8"
        ) as output:
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
        state = result["state"]
        if state == "not_required" or (args.allow_pending and state == "pending"):
            return 0
        # Complete means success or unresolved findings, never failed or pending.
        if args.require_complete and result["reviews_complete"]:
            return 0
        return {"success": 0, "pending": 2, "blocked": 1}[result["state"]]
    except EvidenceError as exc:
        print(f"claude reviews: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
