"""Authenticate completion sources against GitHub REST, never event code.

Sources: https://docs.github.com/en/rest/actions/workflow-runs
https://docs.github.com/en/rest/issues/comments
Pipeline path, name and holds follow this repository's protected merge contract.
"""

from __future__ import annotations

from typing import Any

from ci_codex_review_comments import RECEIPT
from ci_codex_reviews import BOT, SUMMARY, EvidenceError, SHA_PATTERN, _api, _eligible

Record = dict[str, Any]


def positive(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise EvidenceError("protocol")
    return value


def records(endpoint: str, key: str | None = None) -> list[Record]:
    pages = _api(endpoint, paginate=True)
    if not isinstance(pages, list):
        raise EvidenceError("protocol")
    rows = []
    expected = None
    for page in pages:
        if key:
            count = page.get("total_count") if isinstance(page, dict) else None
            if type(count) is not int or count < 0:
                raise EvidenceError("protocol")
            if expected is not None and count != expected:
                raise EvidenceError("protocol")
            expected = count
        items = page.get(key) if isinstance(page, dict) and key else page
        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise EvidenceError("protocol")
        rows.extend(items)
    if key and (expected is None or len(rows) != expected):
        raise EvidenceError("protocol")
    return rows


def bot(user: Any) -> bool:
    return (
        isinstance(user, dict)
        and user.get("login") == BOT
        and user.get("type") == "Bot"
    )


def canonical(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and bot(item.get("user"))
        and isinstance(item.get("body"), str)
        and item["body"].startswith((SUMMARY, RECEIPT))
    )


def live_pr(repo: str, number: int, sha: str | None = None) -> Record | None:
    pull = _api(f"repos/{repo}/pulls/{positive(number)}")
    if not isinstance(pull, dict) or pull.get("number") != number:
        raise EvidenceError("protocol")
    for field in ("head", "base"):
        part = pull.get(field)
        if not isinstance(part, dict) or not isinstance(part.get("repo"), dict):
            raise EvidenceError("protocol")
        if not isinstance(part["repo"].get("full_name"), str):
            raise EvidenceError("protocol")
        positive(part["repo"].get("id"))
    if not isinstance(pull["head"].get("ref"), str):
        raise EvidenceError("protocol")
    head = pull["head"].get("sha")
    if not isinstance(head, str) or SHA_PATTERN.fullmatch(head) is None:
        raise EvidenceError("protocol")
    if not isinstance(pull.get("state"), str) or type(pull.get("draft")) is not bool:
        raise EvidenceError("protocol")
    if not isinstance(pull["base"].get("ref"), str):
        raise EvidenceError("protocol")
    title, labels = pull.get("title"), pull.get("labels")
    if not isinstance(title, str) or not isinstance(labels, list):
        raise EvidenceError("protocol")
    for label in labels:
        if not isinstance(label, dict) or not isinstance(label.get("name"), str):
            raise EvidenceError("protocol")
    try:
        _eligible(pull, repo, head if sha is None else sha)
    except EvidenceError:
        return None
    if "do not merge" in title.casefold() or any(
        label["name"].casefold() in ("hold", "do-not-merge") for label in labels
    ):
        return None
    return pull


def trusted_run(run: Any, repo: str, sha: str | None = None) -> bool:
    if not isinstance(run, dict):
        raise EvidenceError("protocol")
    for field in ("id", "run_number", "run_attempt"):
        positive(run.get(field))
    for field in ("repository", "head_repository"):
        part = run.get(field)
        if not isinstance(part, dict) or not isinstance(part.get("full_name"), str):
            raise EvidenceError("protocol")
        positive(part.get("id"))
    for field in ("name", "path", "event", "head_sha", "head_branch", "status"):
        if not isinstance(run.get(field), str):
            raise EvidenceError("protocol")
    if SHA_PATTERN.fullmatch(run["head_sha"]) is None:
        raise EvidenceError("protocol")
    if run.get("conclusion") is not None and not isinstance(run["conclusion"], str):
        raise EvidenceError("protocol")
    prs = run.get("pull_requests")
    if not isinstance(prs, list):
        raise EvidenceError("protocol")
    for pr in prs:
        if not isinstance(pr, dict):
            raise EvidenceError("protocol")
        positive(pr.get("number"))
    return (
        run["repository"]["full_name"].casefold() == repo.casefold()
        and run["head_repository"]["full_name"].casefold() == repo.casefold()
        and run["name"] == "Pipeline"
        and run["path"] == ".github/workflows/pipeline.yml"
        and run["event"] == "pull_request"
        and (sha is None or run["head_sha"] == sha)
    )


def _associated(run: Record, pull: Record, number: int) -> bool:
    if run["head_branch"] != pull["head"]["ref"]:
        return False
    for field, part in (("repository", "base"), ("head_repository", "head")):
        if run[field]["id"] != pull[part]["repo"]["id"]:
            return False
    matches = [pr for pr in run["pull_requests"] if pr["number"] == number]
    if len(matches) != 1:
        return False
    association = matches[0]
    for part in ("head", "base"):
        item = association.get(part)
        if not isinstance(item, dict) or not isinstance(item.get("repo"), dict):
            raise EvidenceError("protocol")
        if positive(item["repo"].get("id")) != pull[part]["repo"]["id"]:
            return False
    return (
        association["head"].get("ref") == pull["head"]["ref"]
        and association["head"].get("sha") == pull["head"]["sha"]
        and association["base"].get("ref") == "main"
    )


def latest(repo: str, sha: str, number: int) -> Record | None:
    pull = live_pr(repo, number, sha)
    if pull is None:
        return None
    runs = records(
        f"repos/{repo}/actions/workflows/pipeline.yml/runs?event=pull_request&head_sha={sha}",
        "workflow_runs",
    )
    ordered = sorted(
        runs,
        key=lambda run: (positive(run.get("run_number")), positive(run.get("id"))),
        reverse=True,
    )
    for chosen in ordered:
        current = _api(f"repos/{repo}/actions/runs/{chosen['id']}")
        if not isinstance(current, dict) or current.get("id") != chosen["id"]:
            raise EvidenceError("protocol")
        trusted = trusted_run(current, repo, sha)
        if not _associated(current, pull, number):
            continue
        return (
            current
            if (
                trusted
                and current["status"] == "completed"
                and current.get("conclusion") in ("failure", "success")
            )
            else None
        )
    return None


def _comment(event: Record, repo: str) -> Record | None:
    issue, item = event.get("issue"), event.get("comment")
    if not isinstance(issue, dict) or not isinstance(issue.get("pull_request"), dict):
        return None
    if event.get("action") not in ("created", "edited") or not canonical(item):
        return None
    number, identity = positive(issue.get("number")), positive(item.get("id"))
    actual = _api(f"repos/{repo}/issues/comments/{identity}")
    if not canonical(actual):
        return None
    if actual.get("id") != identity:
        raise EvidenceError("protocol")
    if (
        actual.get("issue_url")
        != "https://api.github.com/repos/" + repo + f"/issues/{number}"
    ):
        return None
    return {"number": number, "sha": None, "run_id": None}


def _workflow(event: Record, repo: str) -> Record | None:
    item = event.get("workflow_run")
    if event.get("action") != "completed" or not isinstance(item, dict):
        return None
    identity = positive(item.get("id"))
    actual = _api(f"repos/{repo}/actions/runs/{identity}")
    if (
        not trusted_run(actual, repo)
        or actual["status"] != "completed"
        or actual.get("conclusion") not in ("failure", "success")
    ):
        return None
    if actual["id"] != identity:
        raise EvidenceError("protocol")
    prs = actual["pull_requests"] or records(
        f"repos/{repo}/commits/{actual['head_sha']}/pulls"
    )
    numbers = {positive(pr.get("number")) for pr in prs}
    eligible = [
        number for number in numbers if live_pr(repo, number, actual["head_sha"])
    ]
    if len(eligible) != 1:
        return None
    return {"number": eligible[0], "sha": actual["head_sha"], "run_id": identity}


def event_pr(name: str, event: Record, repo: str) -> Record | None:
    if name not in ("issue_comment", "workflow_run"):
        return None
    repository = event.get("repository")
    if not isinstance(repository, dict) or not isinstance(
        repository.get("full_name"), str
    ):
        raise EvidenceError("event")
    if repository["full_name"].casefold() != repo.casefold():
        return None
    if name in ("issue_comment", "pull_request_review") and not bot(
        event.get("sender")
    ):
        return None
    handler = {
        "issue_comment": _comment,
        "workflow_run": _workflow,
    }.get(name)
    return handler(event, repo) if handler else None
