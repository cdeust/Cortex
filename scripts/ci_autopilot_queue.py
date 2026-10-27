"""Queue policy: owner request2026-10-27, serial Codex repairs and protected merge."""

import hashlib
import json

HOLDS = {"hold", "do-not-merge", "autopilot:hold"}


def held(item: dict) -> bool:
    labels = {row["name"].lower() for row in item.get("labels", [])}
    return bool(labels & HOLDS) or "do not merge" in item["title"].lower()


def fingerprint(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()


def candidates(pulls: list[dict], issues: list[dict]) -> list[dict]:
    result = []
    for pull in pulls:
        if pull["isDraft"] or pull["isCrossRepository"] or held(pull):
            continue
        checks = pull["statusCheckRollup"]
        if any(
            row.get("status") in ("QUEUED", "IN_PROGRESS", "PENDING")
            or row.get("state") in ("PENDING", "EXPECTED")
            for row in checks
        ):
            continue
        indexed = {row.get("name", row.get("context")): row for row in checks}
        ready = indexed.get("merge", {}).get("conclusion") == "SUCCESS"
        result.append(
            {
                "kind": "merge" if ready else "pull",
                "number": pull["number"],
                "sha": pull["headRefOid"],
                "fingerprint": fingerprint(pull),
            }
        )
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
