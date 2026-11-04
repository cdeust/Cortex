"""Authenticated GitHub comment metadata and native Bot edit attribution.

Sources: IssueComment.editor/lastEditedAt and Bot.id, returned with the body.
https://docs.github.com/en/graphql/reference/issues#issuecomment
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

Record = dict[str, Any]
# Source: native Codex summary6456275844 on2026-10-28.
BOT = "chatgpt-codex-connector[bot]"
SUMMARY = "<!-- codex-pull-request-review-summary -->"
STAMP_PATTERN = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z")


def _runtime():
    """The runtime module, resolved on use: runtime imports this module lazily too."""
    import ci_codex_review_runtime as runtime  # noqa: PLC0415 - keeps the import graph acyclic

    return runtime


def _api(*args: Any, **kwargs: Any) -> Any:
    return _runtime()._api(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "EvidenceError":
        return _runtime().EvidenceError
    raise AttributeError(name)


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


def _authenticate_editor(comment: Record, login: str = "chatgpt-codex-connector") -> None:
    # source: IssueComment.editor/lastEditedAt and Bot.id, queried with the body.
    if "editor" not in comment or "lastEditedAt" not in comment:
        raise _runtime().EvidenceError("editor")
    identity = comment.get("user", {}).get("node_id")
    if not isinstance(identity, str) or not identity:
        raise _runtime().EvidenceError("editor")
    editor, edited = comment["editor"], comment["lastEditedAt"]
    if edited is None:
        if editor is not None:
            raise _runtime().EvidenceError("editor")
        return
    if not isinstance(edited, str) or STAMP_PATTERN.fullmatch(edited) is None:
        raise _runtime().EvidenceError("editor")
    try:
        datetime.fromisoformat(edited.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _runtime().EvidenceError("editor") from exc
    if (
        not isinstance(editor, dict)
        or editor.get("__typename") != "Bot"
        or editor.get("login") != login
        or editor.get("id") != identity
    ):
        raise _runtime().EvidenceError("editor")


# Source: native receipts6491350304 (cortex-viz PR213) and6491478435 (Cortex
# PR829), 2026-10-29: posted with the summary's security flags still null.
# Survey of 13 security receipts in 36 cdeust PRs on 2026-10-29: all state no
# issues; two automatic ones (spec PR163 receipt6491660443) add the suffix below.
RECEIPT = "<!-- codex-review-receipt:v1 -->\n"
SECURITY_HEADING = re.compile(
    r"\n### 🛡️ Codex Security Review(?: · _Automatically triggered_)?\n"
)
RECEIPT_COMMIT = re.compile(r"\n\*\*Reviewed commit:\*\* `([0-9a-f]{10,40})`\n")
# The whole no-issues receipt, byte-identical across the six captured ones up to
# the commit prefix, task id and automatic suffix (Codex finding4411675624: the
# verdict is the exact text, never a sentence found somewhere in the body).
NO_ISSUES_RECEIPT = re.compile(
    re.escape(RECEIPT)
    + r"\n### 🛡️ Codex Security Review(?: · _Automatically triggered_)?\n\n"
    r"Security review completed\. No security issues were found in this pull request\.\n\n"
    r"\*\*Reviewed commit:\*\* `[0-9a-f]{10,40}`\n\n"
    r"\[View security finding report\]"
    r"\(https://chatgpt\.com/codex/cloud/tasks/task_e_[0-9a-f]+\)\n\n"
    r"_Only the user who started this review can view the report in Codex\._\n\n"
    + re.escape(
        "<details> <summary>ℹ️ About Codex security reviews in GitHub</summary>\n<br/>\n\n"
        "This is an experimental Codex feature. Security reviews are triggered when:\n"
        '- You comment "@codex security review"\n'
        '- A regular code review gets triggered (for example, "@codex review" or when a'
        " PR is opened), and you’re opted in so security review runs alongside code review\n\n"
        "Once complete, Codex will leave suggestions, or a comment if no findings are found.\n\n\n"
        "</details>"
    )
)
# A completed null verdict without a receipt, or a receipt whose wording no
# observed receipt has, blocks under its own name (the gate never relaunches).
MISSING, UNRECOGNIZED = "verdict_missing", "receipt_unrecognized"
BLOCKING = ("failed", "unresolved", MISSING, UNRECOGNIZED)
BLOCKED_REASONS = (
    ("failed", "review_failed"),
    (MISSING, "codex_security_verdict_missing"),
    (UNRECOGNIZED, "codex_security_receipt_unrecognized"),
)


def _receipt_head(repo: str, named: str) -> str | None:
    """The full commit a receipt names, never a prefix match on the head.

    A 10-hex prefix is 40 bits: a branch writer can make two commits share it
    (Codex finding Cortex PR836 discussion_r4412420778). 40 hex compares exactly;
    a shorter prefix counts only when the repository resolves it to one commit.
    A 404, an ambiguous prefix (422) or any API failure proves nothing.
    https://docs.github.com/en/rest/commits/commits#get-a-commit
    """
    if len(named) == 40:
        return named
    try:
        commit = _api(f"repos/{repo}/commits/{named}")  # late-bound runtime API
    except _runtime().EvidenceError:
        return None
    full = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(full, str) or re.fullmatch(r"[0-9a-f]{40}", full) is None:
        return None
    return full if full.startswith(named) else None


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
        if len(commits) != 1 or _receipt_head(repo, commits[0]) != sha:
            continue
        _authenticate_editor(comment)
        if NO_ISSUES_RECEIPT.fullmatch(body) is None:
            return {"state": UNRECOGNIZED, "source": "codex_security_receipt",
                    "receipt_ids": [comment["id"]]}
        receipts.append(comment["id"])
    return {
        "state": "success" if receipts else MISSING,
        "source": "codex_security_receipt",
        "receipt_ids": sorted(receipts),
    }


# Rule D5, 2026-10-29: Claude skips Dependabot (no Actions secrets, PR #224), so an absent
# marker agrees on a PR by GraphQL author dependabot/Bot on dependabot/* (prD evidence, PR212).
DEPENDABOT = {"login": "dependabot", "__typename": "Bot"}


class Comments(list):
    """Comment rows of one PR, read with its author from the same GraphQL node."""
    dependabot = False


# Body and edit attribution must come from the same authenticated API node.
# https://docs.github.com/en/graphql/reference/issues#issuecomment
COMMENTS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number headRefOid headRefName author { login __typename }
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
    keys = ("databaseId", "body", "updatedAt", "author", "editor", "lastEditedAt")
    if not isinstance(node, dict) or any(key not in node for key in keys):
        raise _runtime().EvidenceError("protocol")
    identity = node["databaseId"]
    if type(identity) is not int or identity <= 0 or not isinstance(node["body"], str):
        raise _runtime().EvidenceError("protocol")
    author = node["author"] or {}
    if not isinstance(author, dict):
        raise _runtime().EvidenceError("protocol")
    login, kind = author.get("login"), author.get("__typename")
    if login in ("chatgpt-codex-connector", "claude") and kind == "Bot":
        login += "[bot]"  # REST form; GraphQL Bot logins omit it (prD evidence).
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
        raise _runtime().EvidenceError("protocol")
    rows, identities, cursors = Comments(), set(), set()
    try:
        for index, page in enumerate(pages):
            if page.get("errors"):
                raise _runtime().EvidenceError("protocol")
            pull = page["data"]["repository"]["pullRequest"]
            if index == 0:  # Same node as the comments; absent fields mean not Dependabot.
                who, ref = pull.get("author"), str(pull.get("headRefName"))
                rows.dependabot = who == DEPENDABOT and ref.startswith("dependabot/")
            if pull["headRefOid"] != sha:
                raise _runtime().EvidenceError("head_moved")
            if type(pull["number"]) is not int or pull["number"] != pr:
                raise _runtime().EvidenceError("protocol")
            connection = pull["comments"]
            more, cursor = (
                connection["pageInfo"][key] for key in ("hasNextPage", "endCursor")
            )
            if type(more) is not bool or more != (index < len(pages) - 1):
                raise _runtime().EvidenceError("protocol")
            if cursor is not None and (not isinstance(cursor, str) or not cursor):
                raise _runtime().EvidenceError("protocol")
            if more and (cursor is None or cursor in cursors):
                raise _runtime().EvidenceError("protocol")
            cursors.add(cursor)
            if not isinstance(connection["nodes"], list):
                raise _runtime().EvidenceError("protocol")
            current = [_comment_row(node) for node in connection["nodes"]]
            current_ids = [row["id"] for row in current]
            if len(set(current_ids)) != len(current_ids) or identities.intersection(
                current_ids
            ):
                raise _runtime().EvidenceError("protocol")
            identities.update(current_ids)
            rows.extend(current)
    except (KeyError, TypeError, AttributeError) as exc:
        raise _runtime().EvidenceError("protocol") from exc
    return rows


def summary_comments(repo: str, pr: int, sha: str, request) -> list[Record]:
    owner, name = repo.split("/")
    fields = dict(query=COMMENTS_QUERY, owner=owner, name=name, number=pr)
    return _comment_pages(request("graphql", paginate=True, fields=fields), sha, pr)
