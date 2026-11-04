"""Trusted Codex review I/O and nullable security-resolution proof.

Sources: PR805 summary6442631163 on0134b085 and authenticated GraphQL
reviewThreads.isResolved, resolvedBy, author.__typename and comment.databaseId.
https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api
https://cli.github.com/manual/gh_api
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from http import HTTPStatus
from pathlib import Path
from typing import Any

Record = dict[str, Any]


class EvidenceError(ValueError):
    """Only fixed diagnostic categories may cross the CLI boundary."""


class APIError(EvidenceError):
    """Sanitized transport category; the existing public reason remains api."""

    def __init__(self, category="unknown"):
        super().__init__("api")
        allowed = ("not_found", "forbidden", "rate_limited")
        self.category = category if category in allowed else "unknown"


def _api_category(output):
    # source: GitHub REST errors expose status; GraphQL errors expose type.
    # https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api
    try:
        payload = _json(output)
    except (EvidenceError, TypeError):
        return "unknown"
    # gh --paginate --slurp wraps a first-page error in one array element.
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    if not isinstance(payload, dict):
        return "unknown"
    try:
        status = HTTPStatus(int(payload.get("status", "")))
    except (ValueError, TypeError):
        status = None
    if status in (HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS):
        return "forbidden" if status == HTTPStatus.FORBIDDEN else "rate_limited"
    errors = payload.get("errors", [])
    if not isinstance(errors, list) or any(not isinstance(row, dict) for row in errors):
        return "unknown"
    types = {row.get("type") for row in errors if isinstance(row.get("type"), str)}
    if "RATE_LIMITED" in types:
        return "rate_limited"
    if status == HTTPStatus.NOT_FOUND or (
        errors and all(row.get("type") == "NOT_FOUND" for row in errors)
    ):
        return "not_found"
    return "unknown"


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
    except subprocess.CalledProcessError as exc:
        raise APIError(_api_category(exc.stdout)) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise APIError() from exc
    return _json(done.stdout)


def _outputs(result: Record) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise EvidenceError("output")
    text = (
        f"ready={str(result['state'] == 'success').lower()}\n"
        f"state={result['state']}\nsha={result['sha']}\ncomment_id={result['comment_id']}\n"
        # Fixed identifiers only: the merge job names why a head cannot merge yet.
        f"reason={result['reason']}\ncauses={','.join(result.get('causes', [result['reason']]))}\n"
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
          resolvedBy { login __typename }
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


def _trusted_resolver(resolver: Any, owner: str) -> bool:
    """Only the repository owner's user account may dismiss a finding.

    source: claude.yml tag-mode rule (ADR-1116, findings4389808387 and
    4390480666) trusts github.repository_owner alone; PR805 finding4391948358
    forbids a PR author resolving their own findings. A missing resolver
    (deleted account, unknown actor) is never trusted.
    """
    if resolver is None:
        return False
    if not isinstance(resolver, dict) or type(resolver.get("login")) is not str:
        raise EvidenceError("protocol")
    return resolver["login"] == owner and resolver.get("__typename") == "User"


def _native_thread(thread: Record, owner: str) -> tuple[int, bool] | None:
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
    return identity, resolved and _trusted_resolver(thread["resolvedBy"], owner)


def _native_states(nodes, owner: str) -> dict[int, bool]:
    states = {}
    for thread in nodes:
        native = _native_thread(thread, owner)
        if native is None:
            continue
        identity, resolved = native
        if identity in states:
            raise EvidenceError("protocol")
        states[identity] = resolved
    return states


def _thread_states(pages: Any, sha: str, owner: str) -> dict[int, bool]:
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
            current = _native_states(connection["nodes"], owner)
            if states.keys() & current.keys():
                raise EvidenceError("protocol")
            states.update(current)
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("protocol") from exc
    return states


def resolve_security(target, body, review, metadata):
    """Prove findings resolved by the trusted owner, thread by thread.

    Two verdicts come here: an unknown one (null flags), and an explicit clean
    one over findings (has_any_findings true, has_unresolved_findings false).
    Only resolvedBy attributes a resolution, never the summary flag (PR87
    discussion_r4412261213): an explicit clean verdict without that proof is
    unresolved, while an unknown one without it stays None for the receipt.
    """
    proof = _owner_proof(target, body, review, metadata)
    if proof is None and review.get("has_unresolved_findings") is False:
        return {"state": "unresolved", "source": "owner_resolution_unproven"}
    return proof


def _owner_proof(target, body, review, metadata):
    """Raw flags remain unchanged; incomplete pages or identities prove nothing."""
    repo, pr, sha = target
    if (
        review.get("status") != "completed"
        or review.get("commit_sha") != sha
        or review.get("has_any_findings") is not True
        or review.get("has_unresolved_findings") not in (None, False)
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
    pages = _api("graphql", paginate=True, fields=fields)
    states = _thread_states(pages, sha, owner)
    if not expected.issubset(states):
        raise EvidenceError("protocol")
    return {
        "state": (
            "success"
            if all(states[identity] for identity in expected)
            else "unresolved"
        ),
        "source": "github_review_threads",
        "finding_ids": sorted(expected),
    }


# Body and edit attribution live in the shared comment boundary.
def _comment_pages(pages: Any, sha: str, pr: int) -> list[Record]:
    from ci_codex_review_comments import _comment_pages as normalize  # noqa: PLC0415 - import cycle: comments shares RuntimeEvidenceError

    return normalize(pages, sha, pr)


def summary_comments(repo: str, pr: int, sha: str, request) -> list[Record]:
    from ci_codex_review_comments import summary_comments as fetch  # noqa: PLC0415 - import cycle: comments shares RuntimeEvidenceError

    return fetch(repo, pr, sha, request)
