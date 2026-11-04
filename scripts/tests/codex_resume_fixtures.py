"""Native completion fixtures adapted from the reviewed Cortex contracts."""

# source: https://github.com/cdeust/Cortex/tree/f4831d159c181b5e170c984f703ed733819f188e/tests_py/scripts
import copy
import json

SHA = "a" * 40

OTHER = "b" * 40

SUMMARY = "<!-- codex-pull-request-review-summary -->"

STATE = "<!-- codex-review-state:v1 "

BOT_NODE_ID = "BOT_kgDOC98s_g"

# source: GraphQL author of claude-mods PR51 comment6494419619 (prD evidence).
CLAUDE_NODE_ID = "BOT_kgDODIGtWg"


def state(sha=SHA):
    review = {
        "commit_sha": sha,
        "status": "completed",
        "has_any_findings": False,
        "has_unresolved_findings": False,
    }
    return {
        "code_review": copy.deepcopy(review),
        "security_review": copy.deepcopy(review),
    }


def comment(data=None, comment_id=1, updated="2026-10-26T22:00:00Z"):
    return {
        "id": comment_id,
        "updated_at": updated,
        "user": {
            "login": "chatgpt-codex-connector[bot]",
            "type": "Bot",
            "node_id": BOT_NODE_ID,
        },
        "editor": None,
        "lastEditedAt": None,
        "body": SUMMARY
        + "\n"
        + STATE
        + json.dumps(state() if data is None else data)
        + " -->",
    }


def claude_verdict(merge=True, sha=SHA, comment_id=900001, updated="2026-10-26T22:05:00Z"):
    """The native Claude review's final comment, ending with its verdict marker."""
    marker = json.dumps({"head": sha, "merge": merge}, separators=(",", ":"))
    return {
        "id": comment_id,
        "updated_at": updated,
        "user": {"login": "claude[bot]", "type": "Bot", "node_id": CLAUDE_NODE_ID},
        "editor": None,
        "lastEditedAt": None,
        "body": "I found no blocking issue.\n\n<!-- claude-review-verdict:v1 " + marker + " -->\n",
    }


def _graphql_comment(row):
    author = copy.deepcopy(row["user"])
    if isinstance(author, dict):
        login = author.get("login")
        author = {
            "login": login.removesuffix("[bot]") if isinstance(login, str) else login,
            "__typename": author.get("type"),
            "id": author.get("node_id"),
        }
    return {
        "databaseId": row["id"],
        "body": row["body"],
        "updatedAt": row["updated_at"],
        "author": author,
        "editor": copy.deepcopy(row["editor"]),
        "lastEditedAt": row["lastEditedAt"],
    }


def with_claude(rows, sha=SHA):
    """The rows of a head on which Claude also concluded merge.

    Owner rule 2026-10-29: Codex and Claude must both conclude for the head.
    """
    return [*rows, claude_verdict(sha=sha)]


def summary_pages(pages, *, number=797, sha=SHA):
    """Capture GraphQL comments with body and editor metadata in each node."""
    result = []
    for index, rows in enumerate(pages):
        more = index < len(pages) - 1
        result.append(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "number": number,
                            "headRefOid": sha,
                            "comments": {
                                "pageInfo": {
                                    "hasNextPage": more,
                                    "endCursor": f"page-{index}" if more else None,
                                },
                                "nodes": [_graphql_comment(row) for row in rows],
                            },
                        }
                    }
                }
            }
        )
    return result


def pull():
    return {
        "number": 797,
        "state": "open",
        "draft": False,
        "head": {"sha": SHA, "repo": {"full_name": "cdeust/Cortex"}},
        "base": {"ref": "main", "repo": {"full_name": "cdeust/Cortex"}},
    }
