"""Queue policy: owner request 2026-10-27, serial Codex repairs and protected merge."""

import hashlib
import json

from ci_codex_review_resume import PREREQUISITES

# source: owner rule 2026-10-29. `hold`/`autopilot:hold` mean "reviews
# incomplete": the PR still needs repair, and
# scripts/ci_autopilot_converge_plan.py lifts them once both reviewers agree.
HOLDS = {"do-not-merge"}


def held(item: dict) -> bool:
    labels = {row["name"].lower() for row in item.get("labels", [])}
    return bool(labels & HOLDS) or "do not merge" in item["title"].lower()


def fingerprint(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()


def pull_candidate(pull):
    if pull["isDraft"] or pull["isCrossRepository"] or held(pull):
        return None
    checks = pull["statusCheckRollup"]
    if any(
        row.get("status")
        in ("QUEUED", "IN_PROGRESS", "PENDING", "REQUESTED", "WAITING")
        or row.get("state") in ("PENDING", "EXPECTED")
        for row in checks
    ):
        return None
    indexed = {row.get("name", row.get("context")): row for row in checks}
    ready = indexed.get("merge", {}).get("conclusion") == "SUCCESS"
    waiting = review_wait(indexed)
    if (
        indexed.get("merge pending review", {}).get("conclusion") == "SUCCESS"
        and "merge" not in indexed
        and not waiting
        and all(
            row.get("conclusion") in ("SUCCESS", "SKIPPED", "NEUTRAL")
            for row in indexed.values()
        )
    ):
        return None
    return {
        "kind": "merge" if ready else ("review_resume" if waiting else "pull"),
        "number": pull["number"],
        "sha": pull["headRefOid"],
        "fingerprint": fingerprint(pull),
    }


def candidates(pulls: list[dict], issues: list[dict]) -> list[dict]:
    result = [item for pull in pulls if (item := pull_candidate(pull)) is not None]
    for issue in issues:
        if issue.get("authorized") is True and not held(issue):
            result.append(
                {
                    "kind": "issue",
                    "number": issue["number"],
                    "fingerprint": issue["revision"],
                    "snapshot": issue["snapshot"],
                }
            )
    return result


def review_wait(indexed: dict) -> bool:
    """Only completed review/merge waits merit the more expensive evidence read."""
    if not all(
        indexed.get(name, {}).get("conclusion") == "SUCCESS" for name in PREREQUISITES
    ):
        return False
    if any(
        row.get("conclusion", row.get("state")) not in ("SUCCESS", "SKIPPED", "NEUTRAL")
        for name, row in indexed.items()
        if name not in ("review", "merge")
    ):
        return False
    waiting = indexed.get("merge pending review", {}).get("conclusion") == "SUCCESS"
    failed = any(
        indexed.get(name, {}).get("conclusion") == "FAILURE"
        for name in ("review", "merge")
    )
    return (waiting and "merge" not in indexed) or failed
