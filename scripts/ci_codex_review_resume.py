"""Resume only a gate that waited for authenticated Codex completion.

Sources: pipeline.yml job/step contract; GitHub REST workflow jobs:
https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-job-from-a-workflow-run
The API reruns the selected job and its dependent jobs. No timers or retry caps:
successful readiness cannot match its previous failed-step predicate again.
"""

from typing import Any

Record = dict[str, Any]
BASE_CATEGORIES = ("contract", "unit", "regression", "e2e")
PREREQUISITES = BASE_CATEGORIES + tuple(
    f"{kind} ({os})"
    for kind in ("environment", "install")
    for os in ("ubuntu-latest", "macos-latest", "windows-latest")
)
READINESS = ("Require completed Codex reviews",)
MERGE = ("Require complete Codex reviews",)


def _success(job: Record) -> bool:
    return job.get("status") == "completed" and job.get("conclusion") == "success"


def _waited(job: Record, names: tuple[str, ...]) -> bool:
    steps = job.get("steps")
    if (
        job.get("status") != "completed"
        or job.get("conclusion") != "failure"
        or not isinstance(steps, list)
        or any(not isinstance(item, dict) for item in steps)
    ):
        return False
    failed = [item.get("name") for item in steps if item.get("conclusion") == "failure"]
    return (
        len(failed) == 1
        and failed[0] in names
        and all(
            item.get("conclusion") in ("success", "failure", "skipped")
            for item in steps
        )
    )


def _repair_dependencies(indexed: dict[str, Record]) -> bool:
    # https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idif
    # Job-level if runs before matrix expansion. Failed
    # tests may therefore leave an unexpanded skipped environment/install job.
    # Repair must consume failed tests; merge still requires all successes.
    if any(name not in indexed for name in BASE_CATEGORIES):
        return False
    if any(
        job.get("status") != "completed"
        or job.get("conclusion") not in ("success", "failure", "skipped")
        for job in indexed.values()
    ):
        return False
    for category in ("environment", "install"):
        expanded = [name for name in PREREQUISITES if name.startswith(category + " (")]
        if category in indexed:
            if indexed[category]["conclusion"] != "skipped" or any(
                name in indexed for name in expanded
            ):
                return False
        elif any(name not in indexed for name in expanded):
            return False
    return True


def _index(jobs: list[Record]) -> dict[str, Record] | None:
    """Index jobs by unique name and unique positive integer id, else None."""
    indexed: dict[str, Record] = {}
    identities: set[int] = set()
    for job in jobs:
        if not isinstance(job, dict):
            return None
        name, identity = job.get("name"), job.get("id")
        if (
            not isinstance(name, str)
            or name in indexed
            or type(identity) is not int
            or identity <= 0
            or identity in identities
        ):
            return None
        indexed[name] = job
        identities.add(identity)
    return indexed


def _green_wait(indexed: dict[str, Record]) -> bool:
    return (
        "merge" not in indexed
        and _success(indexed.get("merge pending review", {}))
        and _success(indexed.get("review", {}))
        and all(_success(indexed.get(name, {})) for name in PREREQUISITES)
        and all(
            job.get("conclusion") in ("success", "skipped") for job in indexed.values()
        )
    )


def _complete_inputs(source: Any, jobs: Any, proof: Any, sha: str) -> bool:
    """A completed run of this head and a complete proof for the same head."""
    return (
        isinstance(source, dict)
        and isinstance(proof, dict)
        and source.get("status") == "completed"
        and source.get("conclusion") in ("failure", "success")
        and source.get("head_sha") == sha
        and proof.get("sha") == sha
        and proof.get("reviews_complete") is True
        and (proof.get("state"), proof.get("reason"))
        in (("success", "reviews_complete"), ("blocked", "review_unresolved"))
        and isinstance(jobs, list)
    )


def resumption_plan(
    source: Record, jobs: list[Record], proof: Record, sha: str
) -> Record:
    """Consume server-verified run/jobs and the normalized evidence reader output."""
    none = {"action": "none"}
    if not _complete_inputs(source, jobs, proof, sha):
        return none
    indexed = _index(jobs)
    if indexed is None:
        return none
    review, merge = indexed.get("review", {}), indexed.get("merge", {})
    if source.get("conclusion") == "success":
        return (
            {"action": "review", "job_id": review["id"]}
            if _green_wait(indexed)
            else none
        )
    if _waited(review, READINESS) and _repair_dependencies(indexed):
        return {"action": "review", "job_id": review["id"]}
    if any(not _success(indexed.get(name, {})) for name in PREREQUISITES):
        return none
    if any(
        job.get("conclusion")
        in ("failure", "cancelled", "timed_out", "action_required")
        for name, job in indexed.items()
        if name not in ("review", "merge")
    ):
        return none
    if _success(review) and _waited(merge, MERGE) and proof["state"] == "success":
        return {"action": "merge", "job_id": merge["id"]}
    return none
