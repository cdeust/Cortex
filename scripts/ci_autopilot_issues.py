"""Authenticate issue revisions before local account-backed execution.

Source: native Codex security finding4384663989 and SECURITY.md trust boundary.
Only owner-authored/edited requirements auto-authorize. Other authors need an
owner comment binding the complete issue snapshot SHA256, not an unbound label.
"""

import re

from ci_autopilot_queue import fingerprint

APPROVAL = re.compile(r"^<!-- cortex-autopilot:approve sha256=([0-9a-f]{64}) -->$")
QUERY = """query($owner:String!, $name:String!, $endCursor:String) {
 repository(owner:$owner,name:$name) {
  issues(first:100,after:$endCursor,states:OPEN) {
   nodes { number title body author { login } editor { login }
    labels(first:100) { nodes { name } }
    comments(first:100) { totalCount nodes {
      databaseId body updatedAt author { login }
    } }
   } pageInfo { hasNextPage endCursor }
  }
 }
}"""


def actor(value):
    return value.get("login") if isinstance(value, dict) else None


def authorize(issue, owner):
    comments = issue["comments"]
    approvals = [
        row
        for row in comments
        if actor(row["author"]) == owner and APPROVAL.fullmatch(row["body"])
    ]
    own = actor(issue["author"]) == owner and actor(issue["editor"]) in (None, owner)
    discussion = [
        row
        for row in comments
        if row not in approvals and (not own or actor(row["author"]) == owner)
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


def intake(options, github):
    owner, name = options.repository.split("/")
    pages = github(
        options,
        "api",
        "graphql",
        "--paginate",
        "--slurp",
        "-f",
        "query=" + QUERY,
        "-F",
        "owner=" + owner,
        "-F",
        "name=" + name,
    )
    result = []
    for page in pages:
        for node in page["data"]["repository"]["issues"]["nodes"]:
            comments = node["comments"]
            if comments["totalCount"] > len(comments["nodes"]):
                comments = rest_comments(options, github, node["number"])
            else:
                comments = comments["nodes"]
            issue = {**node, "comments": comments, "labels": node["labels"]["nodes"]}
            approved = authorize(issue, owner)
            if approved:
                result.append(approved)
    return result


def rest_comments(options, github, number):
    pages = github(
        options,
        "api",
        "--paginate",
        "--slurp",
        f"repos/{options.repository}/issues/{number}/comments?per_page=100",
    )
    return [
        {
            "databaseId": row["id"],
            "body": row["body"],
            "updatedAt": row["updated_at"],
            "author": row["user"],
        }
        for page in pages
        for row in page
    ]
