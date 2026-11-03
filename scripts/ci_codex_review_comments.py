"""Authenticated GitHub comment metadata, native Bot edit attribution, and the
Codex +1 reaction read (REST issues/{pr}/reactions) for null verdicts.

Sources: IssueComment.editor/lastEditedAt and Bot.id, returned with the body.
https://docs.github.com/en/graphql/reference/issues#issuecomment
https://docs.github.com/en/rest/reactions/reactions#list-reactions-for-an-issue
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

import ci_codex_review_runtime as runtime
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


# source: PR846 summary 6591745340, one table row per review on the reviewed head.
COMPLETED_ROW = re.compile(
    r"^\|[^|\n]*\*\*(Code|Security) Review\*\* \| ✅ \*\*Completed\*\* "
    r'<relative-time datetime="([^"]+)"',
    re.M,
)
# source: the summary lists one Code Review row and one Security Review row.
REVIEW_KINDS = ("Code", "Security")
# source: runtime.FINDING and _announced; any finding text voids the clean path.
FINDING_TEXT = (
    "\n### Security findings\n",
    "<!-- codex-security-review-finding:v1 -->",
)


def _stamp(value: Any) -> datetime:
    if not isinstance(value, str) or STAMP_PATTERN.fullmatch(value) is None:
        raise EvidenceError("protocol")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:  # shape-valid, calendar-invalid (month 13)
        raise EvidenceError("protocol") from exc


# source: Codex summary text, "reacts with 👍 once all reviews finish with no
# findings"; PR846 +1 at 2026-11-03T00:23:49Z, after its last head's Security
# Review row of 00:23:45.38Z and five pushes, so Codex re-dates its +1 per head.
# The reactions API reports that user with type "User", so only the login is read.
def _codex_reactions(repo: str, pr: int) -> dict[str, datetime]:
    pages = runtime._api(f"repos/{repo}/issues/{pr}/reactions", paginate=True)
    try:
        rows = [row for page in pages for row in page]
        return {
            row["content"]: _stamp(row["created_at"])
            for row in rows
            if (row.get("user") or {}).get("login") == BOT
        }
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceError("protocol") from exc


def resolve_no_findings(target, body, review, metadata):
    """Null verdict after completion (PR833, PR846) is clean only with Codex's +1
    not earlier than both Completed rows of this Bot summary (second precision:
    reactions carry seconds, rows microseconds), with no 👀 left and no finding
    text in the summary. A commit date would not do: a later push of an older
    commit keeps its date (PR847 review).
    """
    flags = (review.get("has_any_findings"), review.get("has_unresolved_findings"))
    if flags != (None, None) or not runtime._completed_here(target, review, metadata):
        return None
    if any(marker in body for marker in FINDING_TEXT):
        return None
    rows = COMPLETED_ROW.findall(body)
    if sorted(kind for kind, _ in rows) != sorted(REVIEW_KINDS):
        return None
    marks = _codex_reactions(target[0], target[1])
    finished = max(_stamp(stamp) for _, stamp in rows).replace(microsecond=0)
    if "eyes" in marks or "+1" not in marks or marks["+1"] < finished:
        return None
    return {
        "state": "success",
        "source": "github_reaction",
        "reacted_at": marks["+1"].strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
