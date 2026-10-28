"""Authenticate issue revisions using same-response author/editor identities.

Sources: GitHub GraphQL Issue, IssueComment, User; native security finding
4384663989. Owner identity and editor fields verified with GitHub on 2026-10-28.
https://docs.github.com/en/graphql/reference/objects#issuecomment
"""

from datetime import datetime
import re

from ci_autopilot_queue import fingerprint

# source: owner approval protocol introduced by Cortex PR800.
APPROVAL = re.compile(r"^<!-- cortex-autopilot:approve sha256=([0-9a-f]{64}) -->$")
# source: GitHub GraphQL connections require first/last, bounded at 100 nodes.
ACTOR = "login __typename ... on User { id } ... on Bot { id }"
REVISION = (
    "number title body lastEditedAt author { " + ACTOR + " } editor { " + ACTOR + " }"
)
COMMENTS = """comments(first:100,after:$commentCursor) {
 totalCount nodes { databaseId body updatedAt lastEditedAt
 author { ACTOR } editor { ACTOR } }
 pageInfo { hasNextPage endCursor }
}""".replace("ACTOR", ACTOR)
QUERY = """query($owner:String!, $name:String!, $endCursor:String,
 $commentCursor:String) {
 repository(owner:$owner,name:$name) { owner { login id __typename }
 issues(first:100,after:$endCursor,states:OPEN) {
 nodes { REVISION labels(first:100) { nodes { name } } COMMENTS }
 pageInfo { hasNextPage endCursor }
 } }
}""".replace("REVISION", REVISION).replace("COMMENTS", COMMENTS)
COMMENT_QUERY = """query($owner:String!, $name:String!, $number:Int!,
 $commentCursor:String) {
 repository(owner:$owner,name:$name) { issue(number:$number) { REVISION COMMENTS } }
}""".replace("REVISION", REVISION).replace("COMMENTS", COMMENTS)


def actor(value):
    return value.get("login") if isinstance(value, dict) else None


def identity(value):
    return (
        isinstance(value, dict)
        and value.get("__typename") in ("User", "Bot")
        and isinstance(value.get("id"), str)
        and bool(value["id"])
        and isinstance(value.get("login"), str)
        and bool(value["login"])
    )


def same_actor(value, owner):
    return identity(value) and value == owner


def metadata(row):
    if not identity(row.get("author")) or not {"editor", "lastEditedAt"} <= row.keys():
        return False
    editor, stamp = row["editor"], row["lastEditedAt"]
    if editor is None:
        return stamp is None
    if not identity(editor) or not isinstance(stamp, str):
        return False
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def owned(row, owner):
    return (
        metadata(row)
        and same_actor(row["author"], owner)
        and (row["editor"] is None or same_actor(row["editor"], owner))
    )


def claims_owner(row, owner):
    value = row.get("author")
    return isinstance(value, dict) and (
        value.get("login") == owner["login"] or value.get("id") == owner["id"]
    )


def authorize(issue, owner):
    if not identity(owner) or owner["__typename"] != "User" or not metadata(issue):
        return None
    comments = issue["comments"]
    if any("author" not in row for row in comments):
        return None
    if any(
        claims_owner(row, owner) and not owned(row, owner) for row in [issue, *comments]
    ):
        return None
    approvals = [
        row for row in comments if owned(row, owner) and APPROVAL.fullmatch(row["body"])
    ]
    own = owned(issue, owner)
    discussion = [
        row
        for row in comments
        if row not in approvals and (not own or owned(row, owner))
    ]
    snapshot = {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue["body"],
        "comments": discussion,
    }
    digest = fingerprint(snapshot)
    if not own and not any(
        APPROVAL.fullmatch(row["body"])[1] == digest for row in approvals
    ):
        return None
    return {
        "number": issue["number"],
        "title": issue["title"],
        "labels": issue["labels"],
        "authorized": True,
        "revision": digest,
        "snapshot": snapshot,
    }


def cursor(page, seen):
    more, end = page.get("hasNextPage"), page.get("endCursor")
    if type(more) is not bool or (
        more and (not isinstance(end, str) or not end or end in seen)
    ):
        raise RuntimeError("Issue pagination is unverifiable")
    if more:
        seen.add(end)
    return end if more else None


def comments(options, github, node):
    connection, rows, seen = node["comments"], [], set()
    expected = connection["totalCount"]
    while True:
        rows.extend(connection["nodes"])
        next_cursor = cursor(connection["pageInfo"], seen)
        if not next_cursor:
            ids = [row.get("databaseId") for row in rows]
            if (
                len(rows) != expected
                or len(set(ids)) != len(ids)
                or any(type(value) is not int or value <= 0 for value in ids)
            ):
                raise RuntimeError("Issue comments are incomplete")
            return rows
        fresh = graphql(
            options,
            github,
            COMMENT_QUERY,
            number=node["number"],
            commentCursor=next_cursor,
        )["issue"]
        if any(
            fresh[key] != node[key]
            for key in ("number", "title", "body", "author", "editor", "lastEditedAt")
        ):
            raise RuntimeError("Issue revision changed during pagination")
        connection = fresh["comments"]
        if connection["totalCount"] != expected:
            raise RuntimeError("Issue comments changed during pagination")


def graphql(options, github, query, **variables):
    owner, name = options.repository.split("/")
    args = ["api", "graphql", "-f", "query=" + query]
    for key, value in {"owner": owner, "name": name, **variables}.items():
        args += ["-F" if type(value) is int else "-f", f"{key}={value}"]
    page = github(options, *args)
    if not isinstance(page, dict) or page.get("errors"):
        raise RuntimeError("Issue GraphQL failed")
    return page["data"]["repository"]


def intake(options, github):
    owner = options.repository.split("/")[0]
    result, expected_owner, seen, variables = [], None, set(), {}
    while True:
        repo = graphql(options, github, QUERY, **variables)
        trusted = repo["owner"]
        if (
            not identity(trusted)
            or trusted["login"] != owner
            or trusted["__typename"] != "User"
        ):
            raise RuntimeError("Repository owner is unverifiable")
        if expected_owner is not None and trusted != expected_owner:
            raise RuntimeError("Repository owner changed")
        expected_owner = trusted
        for node in repo["issues"]["nodes"]:
            item = {
                **node,
                "comments": comments(options, github, node),
                "labels": node["labels"]["nodes"],
            }
            approved = authorize(item, trusted)
            if approved:
                result.append(approved)
        end = cursor(repo["issues"]["pageInfo"], seen)
        if end is None:
            return result
        variables = {"endCursor": end}
