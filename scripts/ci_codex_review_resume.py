"""Resume only a gate that waited for authenticated Codex completion.

Sources: pipeline.yml job/step contract; GitHub REST workflow jobs:
https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-job-from-a-workflow-run
The API reruns the selected job and its dependent jobs. No timers or retry caps:
successful readiness cannot match its previous failed-step predicate again.
"""

from typing import Any

Record = dict[str, Any]
PREREQUISITES = ("contract", "unit", "regression", "e2e") + tuple(
    f"{kind} ({os})"
    for kind in ("environment", "install")
    for os in ("ubuntu-latest", "macos-latest", "windows-latest")
)
READINESS = "Require completed Codex reviews for repair"
MERGE = "Require complete Codex reviews"


def _success(job: Record) -> bool:
    return job.get("status") == "completed" and job.get("conclusion") == "success"


def _waited(job: Record, step: str) -> bool:
    steps = job.get("steps")
    if (
        job.get("status") != "completed"
        or job.get("conclusion") != "failure"
        or not isinstance(steps, list)
        or any(not isinstance(item, dict) for item in steps)
    ):
        return False
    failed = [item.get("name") for item in steps if item.get("conclusion") == "failure"]
    return failed == [step] and all(
        item.get("conclusion") in ("success", "failure", "skipped") for item in steps
    )


def resumption_plan(
    source: Record, jobs: list[Record], proof: Record, sha: str
) -> Record:
    """Consume server-verified run/jobs and the normalized evidence reader output."""
    none = {"action": "none"}
    if (
        not isinstance(source, dict)
        or not isinstance(proof, dict)
        or source.get("status") != "completed"
        or source.get("conclusion") != "failure"
        or source.get("head_sha") != sha
        or proof.get("sha") != sha
        or proof.get("reviews_complete") is not True
        or (proof.get("state"), proof.get("reason"))
        not in (("success", "reviews_complete"), ("blocked", "review_unresolved"))
        or not isinstance(jobs, list)
    ):
        return none
    indexed: dict[str, Record] = {}
    identities: set[int] = set()
    for job in jobs:
        if not isinstance(job, dict):
            return none
        name, identity = job.get("name"), job.get("id")
        if (
            not isinstance(name, str)
            or name in indexed
            or type(identity) is not int
            or identity <= 0
            or identity in identities
        ):
            return none
        indexed[name] = job
        identities.add(identity)
    if any(not _success(indexed.get(name, {})) for name in PREREQUISITES):
        return none
    if any(
        job.get("conclusion")
        in ("failure", "cancelled", "timed_out", "action_required")
        for name, job in indexed.items()
        if name not in ("review", "merge")
    ):
        return none
    review, merge = indexed.get("review", {}), indexed.get("merge", {})
    if _waited(review, READINESS):
        return {"action": "review", "job_id": review["id"]}
    if _success(review) and _waited(merge, MERGE) and proof["state"] == "success":
        return {"action": "merge", "job_id": merge["id"]}
    return none
