#!/usr/bin/env python3
"""Resume exact failed Codex gates from authenticated completion events.

Runs only adjacent trusted default-branch modules. No candidate checkout.
Sources: https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-job-from-a-workflow-run
https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt
https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run
Workflow concurrency serializes events; REST rerun offers no head/attempt CAS.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

# The wrapper checks out trusted main; isolated Python may still load these files.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_codex_review_event_source as source  # noqa: E402
from ci_codex_reviews import EvidenceError, REPO_PATTERN, _json, review_evidence  # noqa: E402
from ci_codex_reviews import summary_comments  # noqa: E402
from ci_codex_review_resume import resumption_plan  # noqa: E402

Record = dict[str, Any]
EVENTS = ("issue_comment", "workflow_run")
NONE = {"action": "none"}


def _attempt_jobs(repo: str, run: Record, attempt: int) -> list[Record]:
    rows = source.records(
        f"repos/{repo}/actions/runs/{run['id']}/attempts/{attempt}/jobs",
        "jobs",
    )
    for job in rows:
        for field in ("id", "run_id", "run_attempt"):
            source.positive(job.get(field))
        if (
            job.get("run_id") != run["id"]
            or job.get("run_attempt") != attempt
            or job.get("head_sha") != run["head_sha"]
            or not isinstance(job.get("name"), str)
            or not isinstance(job.get("status"), str)
        ):
            raise EvidenceError("protocol")
        if job.get("conclusion") is not None and not isinstance(job["conclusion"], str):
            raise EvidenceError("protocol")
        steps = job.get("steps", [])
        if not isinstance(steps, list) or any(
            not isinstance(step, dict) for step in steps
        ):
            raise EvidenceError("protocol")
        for step in steps:
            if not isinstance(step.get("name"), str) or (
                step.get("conclusion") is not None
                and not isinstance(step["conclusion"], str)
            ):
                raise EvidenceError("protocol")
    return rows


def _jobs(repo: str, run: Record) -> list[Record]:
    """Keep the newest result per name, including jobs untouched by partial reruns.

    The run/jobs default filter=latest exposes only the most recent execution.
    Read authenticated attempts back to attempt1 to retain the entire original graph,
    including unexpected failures; required job names alone cannot prove this.
    """
    effective: dict[str, Record] = {}
    identities: set[int] = set()
    for attempt in range(source.positive(run["run_attempt"]), 0, -1):
        names: set[str] = set()
        for job in _attempt_jobs(repo, run, attempt):
            if job["name"] in names or job["id"] in identities:
                raise EvidenceError("protocol")
            names.add(job["name"])
            identities.add(job["id"])
            effective.setdefault(job["name"], job)
    # Job-level if precedes expansion; newer children replace skipped placeholders.
    for category in ("environment", "install"):
        if _superseded_placeholder(effective, category):
            del effective[category]
    return list(effective.values())


def _superseded_placeholder(effective: dict[str, Record], category: str) -> bool:
    placeholder = effective.get(category)
    if not placeholder or placeholder["conclusion"] != "skipped":
        return False
    return any(
        name.startswith(category + " (")
        and job["run_attempt"] > placeholder["run_attempt"]
        for name, job in effective.items()
    )


def _proof(repo: str, number: int, run: Record, jobs: list[Record]) -> Record:
    return head_proof(repo, number, run["head_sha"])


def head_proof(repo: str, number: int, sha: str) -> Record:
    rows = summary_comments(repo, number, sha, source._api)
    result = review_evidence(rows, sha, repo, number)
    if result.get("reason") in ("protocol", "arguments"):
        raise EvidenceError("protocol")
    return result


def _plan(run: Record, jobs: list[Record], proof: Record, sha: str) -> Record:
    result = resumption_plan(run, jobs, proof, sha)
    if not isinstance(result, dict):
        raise EvidenceError("protocol")
    if result.get("action") == "none":
        return NONE.copy()
    if result.get("action") not in ("review", "merge"):
        raise EvidenceError("protocol")
    identity = source.positive(result.get("job_id"))
    selected = [job for job in jobs if job["id"] == identity]
    if len(selected) != 1 or selected[0]["run_attempt"] != run["run_attempt"]:
        return NONE.copy()
    return {"action": result["action"], "job_id": identity}


def _post(repo: str, identity: int) -> None:
    endpoint = f"repos/{repo}/actions/jobs/{source.positive(identity)}/rerun"
    try:
        subprocess.run(
            ["gh", "api", "--method", "POST", endpoint],
            text=True,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceError("api") from exc


def _expected_pr() -> int:
    value = os.environ.get("EXPECTED_PR", "")
    if (
        not value
        or not value.isascii()
        or not value.isdecimal()
        or value.startswith("0")
    ):
        raise EvidenceError("environment")
    try:
        return source.positive(int(value))
    except ValueError as exc:
        raise EvidenceError("environment") from exc


def coordinate(name: str, event: Record, repo: str) -> Record:
    if name not in EVENTS:
        return NONE.copy()
    trigger = source.event_pr(name, event, repo)
    if trigger is None:
        return NONE.copy()
    return resume(repo, trigger)


def resume(repo: str, trigger: Record) -> Record:
    """Rerun the waiting gate for a server-derived {number, sha, run_id} trigger."""
    number = trigger["number"]
    if number != _expected_pr():
        return NONE.copy()
    pull = source.live_pr(repo, number, trigger["sha"])
    if pull is None:
        return NONE.copy()
    sha = pull["head"]["sha"]
    run = source.latest(repo, sha, number)
    if run is None or (
        trigger["run_id"] is not None and trigger["run_id"] != run["id"]
    ):
        return NONE.copy()
    jobs = _jobs(repo, run)
    plan = _plan(run, jobs, _proof(repo, number, run, jobs), sha)
    if plan["action"] == "none":
        return plan
    current = source.latest(repo, sha, number)
    if current is None or any(
        current[key] != run[key] for key in ("id", "run_attempt")
    ):
        return NONE.copy()
    fresh_jobs = _jobs(repo, current)
    fresh = _plan(current, fresh_jobs, _proof(repo, number, current, fresh_jobs), sha)
    if fresh != plan or source.live_pr(repo, number, sha) is None:
        return NONE.copy()
    _post(repo, plan["job_id"])
    return plan


def identify(name: str, event: Record, repo: str) -> int | None:
    """Authenticate the event and expose only an eligible server-derived PR number."""
    trigger = source.event_pr(name, event, repo)
    if trigger is None:
        return None
    pull = source.live_pr(repo, trigger["number"], trigger["sha"])
    return trigger["number"] if pull is not None else None


def _identify_output(number: int | None) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise EvidenceError("output")
    value = "" if number is None else str(source.positive(number))
    try:
        with Path(path).open("a", encoding="utf-8") as output:
            output.write(f"pr={value}\n")
    except OSError as exc:
        raise EvidenceError("output") from exc


def main(argv: list[str] | None = None) -> int:
    try:
        flags = sys.argv[1:] if argv is None else argv
        if flags not in ([], ["--identify"]):
            raise EvidenceError("arguments")
        identifying = bool(flags)
        name = os.environ.get("GITHUB_EVENT_NAME", "")
        if name not in EVENTS:
            if identifying:
                _identify_output(None)
            print(json.dumps(NONE))
            return 0
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if (
            REPO_PATTERN.fullmatch(repo) is None
            or repo.split("/")[1] in (".", "..")
            or not os.environ.get("GH_TOKEN")
        ):
            raise EvidenceError("environment")
        event = _json(
            Path(os.environ.get("GITHUB_EVENT_PATH", "")).read_text(encoding="utf-8")
        )
        if not isinstance(event, dict):
            raise EvidenceError("event")
        if identifying:
            number = identify(name, event, repo)
            _identify_output(number)
            result = {"pr": number}
        else:
            result = coordinate(name, event, repo)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, UnicodeError):
        print("codex resume: event", file=sys.stderr)
        return 1
    except EvidenceError as exc:
        print(f"codex resume: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
