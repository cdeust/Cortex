"""Authenticated GitHub comment metadata and native Bot edit attribution.

Sources: IssueComment.editor/lastEditedAt and Bot.id, returned with the body.
https://docs.github.com/en/graphql/reference/issues#issuecomment
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from ci_codex_review_runtime import EvidenceError

Record = dict[str, Any]
# Source: native Codex summary6456275844 on2026-10-28.
BOT = "chatgpt-codex-connector[bot]"
SUMMARY = "<!-- codex-pull-request-review-summary -->"
STAMP_PATTERN = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z")


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


def _bot_author(comment: Record) -> bool:
    user = comment.get("user")
    return (
        isinstance(user, dict)
        and user.get("login") == BOT
        and user.get("type") == "Bot"
    )


def _authenticate_editor(comment: Record) -> None:
    # source: IssueComment.editor/lastEditedAt and Bot.id, queried with the body.
    if "editor" not in comment or "lastEditedAt" not in comment:
        raise EvidenceError("editor")
    identity = comment.get("user", {}).get("node_id")
    if not isinstance(identity, str) or not identity:
        raise EvidenceError("editor")
    editor, edited = comment["editor"], comment["lastEditedAt"]
    if edited is None:
        if editor is not None:
            raise EvidenceError("editor")
        return
    if not isinstance(edited, str) or STAMP_PATTERN.fullmatch(edited) is None:
        raise EvidenceError("editor")
    try:
        datetime.fromisoformat(edited.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("editor") from exc
    if (
        not isinstance(editor, dict)
        or editor.get("__typename") != "Bot"
        or editor.get("login") != "chatgpt-codex-connector"
        or editor.get("id") != identity
    ):
        raise EvidenceError("editor")


# Source: native receipts6491350304 (cortex-viz PR213) and6491478435 (Cortex
# PR829), 2026-10-29: posted with the summary's security flags still null.
# Survey of 13 security receipts in 36 cdeust PRs on 2026-10-29: all state no
# issues; two automatic ones (spec PR163 receipt6491660443) add the suffix below.
RECEIPT = "<!-- codex-review-receipt:v1 -->\n"
SECURITY_HEADING = re.compile(
    r"\n### 🛡️ Codex Security Review(?: · _Automatically triggered_)?\n"
)
NO_SECURITY_ISSUES = (
    "\nSecurity review completed. No security issues were found in this pull request.\n"
)
RECEIPT_COMMIT = re.compile(r"\n\*\*Reviewed commit:\*\* `([0-9a-f]{10,40})`\n")
# A completed null verdict without a receipt, or a receipt whose wording no
# observed receipt has, blocks under its own name (the gate never relaunches).
MISSING, UNRECOGNIZED = "verdict_missing", "receipt_unrecognized"
BLOCKING = ("failed", "unresolved", MISSING, UNRECOGNIZED)
BLOCKED_REASONS = (
    ("failed", "review_failed"),
    (MISSING, "codex_security_verdict_missing"),
    (UNRECOGNIZED, "codex_security_receipt_unrecognized"),
)


def security_receipt(comments, target, review, metadata):
    """Native verdict for a completed security review whose flags stayed null.

    Codex documents an empty result as no proof; its authenticated receipt is the
    report it points to. Every security receipt for this head must state no
    issues; no receipt or any other wording blocks under a named state.
    """
    repo, pr, sha = target
    if (
        review.get("status") != "completed"
        or review.get("commit_sha") != sha
        or review.get("has_any_findings") is not None
        or review.get("has_unresolved_findings") is not None
        or not isinstance(metadata, dict)
        or (metadata.get("repository"), metadata.get("pullRequestNumber")) != (repo, pr)
        or (metadata.get("headSha"), metadata.get("status")) != (sha, "completed")
    ):
        return None
    receipts = []
    for comment in comments:
        body = comment.get("body")
        if not (_bot_author(comment) and isinstance(body, str)):
            continue
        if not body.startswith(RECEIPT) or len(SECURITY_HEADING.findall(body)) != 1:
            continue
        commits = RECEIPT_COMMIT.findall(body)
        if len(commits) != 1 or not sha.startswith(commits[0]):
            continue
        _authenticate_editor(comment)
        if body.count(NO_SECURITY_ISSUES) != 1:
            return {"state": UNRECOGNIZED, "source": "codex_security_receipt",
                    "receipt_ids": [comment["id"]]}
        receipts.append(comment["id"])
    return {
        "state": "success" if receipts else MISSING,
        "source": "codex_security_receipt",
        "receipt_ids": sorted(receipts),
    }


# Body and edit attribution must come from the same authenticated API node.
# https://docs.github.com/en/graphql/reference/issues#issuecomment
COMMENTS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number headRefOid
      comments(first:100, after:$endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          databaseId body updatedAt lastEditedAt
          author { login __typename ... on Bot { id } ... on User { id } }
          editor { login __typename ... on Bot { id } ... on User { id } }
        }
      }
    }
  }
}
"""


def _comment_row(node: Any) -> Record:
    if not isinstance(node, dict) or any(
        key not in node
        for key in (
            "databaseId",
            "body",
            "updatedAt",
            "author",
            "editor",
            "lastEditedAt",
        )
    ):
        raise EvidenceError("protocol")
    identity = node["databaseId"]
    if type(identity) is not int or identity <= 0 or not isinstance(node["body"], str):
        raise EvidenceError("protocol")
    author = node["author"] or {}
    if not isinstance(author, dict):
        raise EvidenceError("protocol")
    login, kind = author.get("login"), author.get("__typename")
    if login == "chatgpt-codex-connector" and kind == "Bot":
        login = "chatgpt-codex-connector[bot]"
    return {
        "id": identity,
        "body": node["body"],
        "updated_at": node["updatedAt"],
        "user": {"login": login, "type": kind, "node_id": author.get("id")},
        "editor": node["editor"],
        "lastEditedAt": node["lastEditedAt"],
    }


def _comment_pages(pages: Any, sha: str, pr: int) -> list[Record]:
    if not isinstance(pages, list) or not pages:
        raise EvidenceError("protocol")
    rows, identities, cursors = [], set(), set()
    try:
        for index, page in enumerate(pages):
            if page.get("errors"):
                raise EvidenceError("protocol")
            pull = page["data"]["repository"]["pullRequest"]
            if pull["headRefOid"] != sha:
                raise EvidenceError("head_moved")
            if type(pull["number"]) is not int or pull["number"] != pr:
                raise EvidenceError("protocol")
            connection = pull["comments"]
            more, cursor = (
                connection["pageInfo"][key] for key in ("hasNextPage", "endCursor")
            )
            if type(more) is not bool or more != (index < len(pages) - 1):
                raise EvidenceError("protocol")
            if cursor is not None and (not isinstance(cursor, str) or not cursor):
                raise EvidenceError("protocol")
            if more and (cursor is None or cursor in cursors):
                raise EvidenceError("protocol")
            cursors.add(cursor)
            if not isinstance(connection["nodes"], list):
                raise EvidenceError("protocol")
            current = [_comment_row(node) for node in connection["nodes"]]
            current_ids = [row["id"] for row in current]
            if len(set(current_ids)) != len(current_ids) or identities.intersection(
                current_ids
            ):
                raise EvidenceError("protocol")
            identities.update(current_ids)
            rows.extend(current)
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceError("protocol") from exc
    return rows


def summary_comments(repo: str, pr: int, sha: str, request) -> list[Record]:
    owner, name = repo.split("/")
    fields = dict(query=COMMENTS_QUERY, owner=owner, name=name, number=pr)
    return _comment_pages(request("graphql", paginate=True, fields=fields), sha, pr)
