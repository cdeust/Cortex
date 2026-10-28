#!/usr/bin/env python3
"""Reconcile native review gates through the existing authenticated coordinator.

Sources: GitHub's supported schedule/workflow_dispatch events and paginated PR API.
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
https://docs.github.com/en/graphql/reference/objects#statuscheckrollup
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_codex_review_event as events  # noqa: E402
from ci_codex_reviews import APIError, EvidenceError, REPO_PATTERN, SHA_PATTERN  # noqa: E402


def _diagnostic(number, category):
    identity = str(number) if type(number) is int else "unknown"
    print(f"codex reconcile: pr={identity} {category}", file=sys.stderr)


# source: GitHub GraphQL connections allow at most 100 nodes per page.
# https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api
DISCOVERY_QUERY = """
query($owner: String!, $name: String!, $endCursor: String) {
  repository(owner:$owner, name:$name) {
    nameWithOwner
    pullRequests(first:100, after:$endCursor, states:OPEN) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title isDraft isCrossRepository headRefOid
        headRepository { nameWithOwner }
        labels(first:100) { nodes { name } }
        commits(last:1) { nodes { commit {
          oid statusCheckRollup { contexts(first:100) {
            pageInfo { hasNextPage }
            nodes {
              __typename
              ... on CheckRun { name status conclusion }
              ... on StatusContext { context state }
            }
          } }
        } } }
      }
    }
  }
}
"""


def _page_nodes(page, repo, expected_more, cursors):
    try:
        repository = page["data"]["repository"]
        connection = repository["pullRequests"]
        nodes, info = connection["nodes"], connection["pageInfo"]
        more = info["hasNextPage"]
        cursor = info["endCursor"]
        valid = (
            not page.get("errors")
            and repository["nameWithOwner"].casefold() == repo.casefold()
            and isinstance(nodes, list)
            and type(more) is bool
            and more == expected_more
        )
        if more:
            valid = (
                valid
                and isinstance(cursor, str)
                and bool(cursor)
                and cursor not in cursors
            )
            cursors.add(cursor)
        if not valid:
            raise EvidenceError("protocol")
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceError("protocol") from exc
    return nodes


def _rows(pages, repo):
    if not isinstance(pages, list) or not pages:
        raise EvidenceError("protocol")
    unique, rejected, cursors = {}, set(), set()
    for index, page in enumerate(pages):
        nodes = _page_nodes(page, repo, index < len(pages) - 1, cursors)
        for row in nodes:
            try:
                number = events.source.positive(row.get("number"))
            except (AttributeError, EvidenceError):
                _diagnostic(None, "protocol")
                continue
            if number in unique or number in rejected:
                unique.pop(number, None)
                rejected.add(number)
                _diagnostic(number, "protocol")
            else:
                unique[number] = row
    return unique.values()


def _possible_wait(repo, row):
    # A cheap superset only: the existing full-proof plan remains the authorizer.
    try:
        if row["isDraft"] is not False or row["isCrossRepository"] is not False:
            return False
        if row["headRepository"]["nameWithOwner"].casefold() != repo.casefold():
            return False
        if "do not merge" in row["title"].casefold() or any(
            item["name"].casefold() in ("hold", "do-not-merge")
            for item in row["labels"]["nodes"]
        ):
            return False
        commits = row["commits"]["nodes"]
        if len(commits) != 1 or commits[0]["commit"]["oid"] != row["headRefOid"]:
            raise EvidenceError("protocol")
        rollup = commits[0]["commit"]["statusCheckRollup"]
        return _rollup_wait(rollup)
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceError("protocol") from exc


def _group_checks(checks):
    grouped = {}
    for item in checks:
        if item.get("__typename") == "CheckRun":
            grouped.setdefault(item["name"], []).append(item)
    return grouped


def _gate_wait(grouped):
    gates = [
        grouped.get(name, []) for name in ("review", "merge", "merge pending review")
    ]
    if any(len(items) > 1 for items in gates):
        return True  # Ambiguous suites are hints for full proof, never a veto.
    if any(
        item.get("status")
        in ("QUEUED", "IN_PROGRESS", "PENDING", "REQUESTED", "WAITING")
        for items in gates
        for item in items
    ):
        return False
    review, merge, pending = gates
    if any(item.get("conclusion") == "FAILURE" for item in review):
        return True  # Readiness repair permits failed test jobs.
    failed_merge = any(item.get("conclusion") == "FAILURE" for item in merge)
    return failed_merge or (
        not merge
        and any(item.get("conclusion") == "SUCCESS" for item in pending)
        and any(item.get("conclusion") == "SUCCESS" for item in review)
    )


def _rollup_wait(rollup):
    try:
        if rollup is None:
            return False
        contexts = rollup["contexts"]
        checks = contexts["nodes"]
        if (
            not isinstance(checks, list)
            or type(contexts["pageInfo"]["hasNextPage"]) is not bool
        ):
            raise EvidenceError("protocol")
        if contexts["pageInfo"]["hasNextPage"]:
            return True  # Incomplete optimization cannot veto actual full policy.
        return _gate_wait(_group_checks(checks))
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceError("protocol") from exc


def _proof_can_resume(row, proof):
    if proof.get("reviews_complete") is not True:
        return False
    if proof.get("state") == "success":
        return True
    contexts = row["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]
    if contexts["pageInfo"]["hasNextPage"]:
        return True  # Partial gate names cannot veto a real readiness repair.
    if any(
        item.get("__typename") == "CheckRun"
        and item.get("name") == "merge pending review"
        and item.get("conclusion") == "SUCCESS"
        for item in contexts["nodes"]
    ):
        return True  # Full policy decides whether this green wait needs repair.
    reviews = [item for item in contexts["nodes"] if item.get("name") == "review"]
    return not reviews or any(item.get("conclusion") != "SUCCESS" for item in reviews)


def _candidate(repo, row):
    number = events.source.positive(row["number"])
    if not _possible_wait(repo, row):
        return None
    sha = row.get("headRefOid")
    if not isinstance(sha, str) or SHA_PATTERN.fullmatch(sha) is None:
        raise EvidenceError("protocol")
    proof = events.head_proof(repo, number, sha)
    if proof.get("reason") == "api":
        raise APIError(proof.get("api_category", "unknown"))
    if not _proof_can_resume(row, proof):
        return None
    run = events.source.latest(repo, sha, number)
    if run is None:
        return None
    jobs = events._jobs(repo, run)
    plan = events._plan(run, jobs, proof, sha)
    return {"number": number, "sha": sha} if plan["action"] != "none" else None


def discover(repo):
    owner, name = repo.split("/")
    pages = events.source._api(
        "graphql",
        paginate=True,
        fields={"query": DISCOVERY_QUERY, "owner": owner, "name": name},
    )
    selected = []
    for row in _rows(pages, repo):
        try:
            candidate = _candidate(repo, row)
        except EvidenceError as exc:
            if str(exc) == "api" and not (
                isinstance(exc, APIError) and exc.category == "not_found"
            ):
                raise
            _diagnostic(
                row["number"],
                "api/not_found" if isinstance(exc, APIError) else "protocol",
            )
            continue
        if candidate is not None:
            selected.append(candidate)
    return selected


def _trigger(flags):
    try:
        pr_flag, number, sha_flag, sha = flags
    except ValueError as exc:
        raise EvidenceError("arguments") from exc
    if (pr_flag, sha_flag) != ("--pr", "--sha"):
        raise EvidenceError("arguments")
    if not number.isascii() or not number.isdecimal() or number.startswith("0"):
        raise EvidenceError("arguments")
    if SHA_PATTERN.fullmatch(sha) is None:
        raise EvidenceError("arguments")
    try:
        number = events.source.positive(int(number))
    except ValueError as exc:
        raise EvidenceError("arguments") from exc
    return {"number": number, "sha": sha, "run_id": None}


def _outputs(result):
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise EvidenceError("output")
    try:
        with Path(path).open("a", encoding="utf-8") as output:
            output.write("prs=" + json.dumps(result) + "\n")
    except OSError as exc:
        raise EvidenceError("output") from exc


def main(argv=None):
    try:
        flags = sys.argv[1:] if argv is None else argv
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if REPO_PATTERN.fullmatch(repo) is None or repo.split("/")[1] in (".", ".."):
            raise EvidenceError("environment")
        if not os.environ.get("GH_TOKEN"):
            raise EvidenceError("environment")
        if flags == ["--list"]:
            result = discover(repo)
            _outputs(result)
        else:
            result = events.resume(repo, _trigger(flags))
        print(json.dumps(result, sort_keys=True))
        return 0
    except EvidenceError as exc:
        print(f"codex reconcile: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
