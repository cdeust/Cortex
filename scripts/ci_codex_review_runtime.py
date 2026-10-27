"""Trusted Codex review I/O and nullable security-resolution proof.

Sources: PR805 summary6442631163 on0134b085 and authenticated GraphQL
reviewThreads.isResolved, author.__typename and comment.databaseId.
https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api
https://cli.github.com/manual/gh_api
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

Record = dict[str, Any]


class EvidenceError(ValueError):
    """Only fixed diagnostic categories may cross the CLI boundary."""


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


def _api(endpoint: str, *, paginate: bool = False, fields: Record | None = None) -> Any:
    # https://cli.github.com/manual/gh_api: --slurp wraps all paginated pages.
    command = ["gh", "api", *(["--paginate", "--slurp"] if paginate else []), endpoint]
    for key, value in (fields or {}).items():
        flag = "--field" if type(value) is int else "--raw-field"
        command.extend((flag, f"{key}={value}"))
    try:
        done = subprocess.run(command, text=True, capture_output=True, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError("api") from exc
    return _json(done.stdout)


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


# first:100 is GitHub's documented maximum connection page, not a score threshold.
THREAD_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      headRefOid
      reviewThreads(first:100, after:$endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          comments(first:1) { nodes { databaseId body author { login __typename } } }
        }
      }
    }
  }
}
"""
FINDING = "<!-- codex-security-review-finding:v1 -->"


def _announced(body: str, repo: str, pr: int) -> set[int]:
    """Require a nonempty, fully enumerated native security finding list."""
    heading = "\n### Security findings\n"
    if body.count(heading) != 1:
        return set()
    section = body.split(heading, 1)[1].split("\n<details>", 1)[0]
    counts = re.findall(
        r"^#### (?:Blocking|Advisory) findings \(([0-9]+)\)$", section, re.M
    )
    prefix = re.escape(f"https://github.com/{repo}/pull/{pr}#discussion_r")
    ids = re.findall(prefix + r"([1-9][0-9]*)\)", section)
    try:
        expected = {int(identity) for identity in ids}
        total = sum(int(count) for count in counts)
    except ValueError as exc:
        raise EvidenceError("protocol") from exc
    return expected if expected and len(expected) == len(ids) == total else set()


def _native_thread(thread: Record) -> tuple[int, bool] | None:
    resolved = thread["isResolved"]
    if type(resolved) is not bool:
        raise EvidenceError("protocol")
    root = thread["comments"]["nodes"][0]
    author = root.get("author") or {}
    if (
        author.get("login") != "chatgpt-codex-connector"
        or author.get("__typename") != "Bot"
        or not root["body"].startswith(FINDING)
    ):
        return None
    identity = root["databaseId"]
    if type(identity) is not int or identity <= 0:
        raise EvidenceError("protocol")
    return identity, resolved


def _native_states(nodes) -> dict[int, bool]:
    states = {}
    for thread in nodes:
        native = _native_thread(thread)
        if native is None:
            continue
        identity, resolved = native
        if identity in states:
            raise EvidenceError("protocol")
        states[identity] = resolved
    return states


def _thread_states(pages: Any, sha: str) -> dict[int, bool]:
    if not isinstance(pages, list) or not pages:
        raise EvidenceError("protocol")
    states = {}
    try:
        for index, page in enumerate(pages):
            if page.get("errors"):
                raise EvidenceError("protocol")
            pull = page["data"]["repository"]["pullRequest"]
            if pull["headRefOid"] != sha:
                raise EvidenceError("head_moved")
            connection = pull["reviewThreads"]
            more = connection["pageInfo"]["hasNextPage"]
            if type(more) is not bool or more != (index < len(pages) - 1):
                raise EvidenceError("protocol")
            current = _native_states(connection["nodes"])
            if states.keys() & current.keys():
                raise EvidenceError("protocol")
            states.update(current)
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("protocol") from exc
    return states


def resolve_security(target, body, review, metadata):
    """Reconcile one unknown verdict with positive, authenticated finding proof.

    Raw flags remain unchanged. Running/stale reviews and explicit verdicts
    never use this path. No findings, incomplete pages or missing identities
    cannot establish a resolved review.
    """
    repo, pr, sha = target
    if (
        review.get("status") != "completed"
        or review.get("commit_sha") != sha
        or review.get("has_any_findings") is not True
        or review.get("has_unresolved_findings") is not None
        or not isinstance(metadata, dict)
        or metadata.get("repository") != repo
        or metadata.get("pullRequestNumber") != pr
        or metadata.get("headSha") != sha
        or metadata.get("status") != "completed"
    ):
        return None
    expected = _announced(body, repo, pr)
    if not expected:
        return None
    owner, name = repo.split("/")
    fields = dict(query=THREAD_QUERY, owner=owner, name=name, number=pr)
    states = _thread_states(_api("graphql", paginate=True, fields=fields), sha)
    if states.keys() != expected:
        raise EvidenceError("protocol")
    return {
        "state": "success" if all(states.values()) else "unresolved",
        "source": "github_review_threads",
        "finding_ids": sorted(states),
    }
