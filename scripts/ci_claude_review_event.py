#!/usr/bin/env python3
"""Target claude[bot] reviews and resume the gate from Pipeline requests.

claude.yml runs this only after checking out trusted main; the event file is a
hint that is re-read through the REST API. --target names the one live
same-repository PR of a first-attempt Pipeline run and the review kinds still
absent on its exact head. The default mode resumes the waiting Pipeline gate
through the shared Codex coordinator, whose proof combines both sources.
Sources: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run
https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run
https://docs.github.com/en/rest/commits/commits#list-pull-requests-associated-with-a-commit
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

# The wrapper checks out trusted main; isolated Python may still load these files.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_claude_reviews as claude  # noqa: E402
import ci_codex_review_event as codex_event  # noqa: E402
import ci_codex_review_event_source as source  # noqa: E402
from ci_codex_reviews import EvidenceError, REPO_PATTERN, _eligible, _json  # noqa: E402

Record = dict[str, Any]
EVENT = "workflow_run"
NONE = {"action": "none"}
EMPTY = {"pr": "", "sha": "", "code": "false", "security": "false"}


def _open(repo: str, number: int, sha: str) -> bool:
    try:
        _eligible(
            source._api(f"repos/{repo}/pulls/{source.positive(number)}"), repo, sha
        )
    except EvidenceError as exc:
        if str(exc) in ("pr_eligibility", "head_moved"):
            return False
        raise
    return True


def target(event: Record, repo: str) -> Record | None:
    """Authenticate one requested first-attempt Pipeline run of one live PR."""
    repository = event.get("repository")
    if not isinstance(repository, dict) or not isinstance(
        repository.get("full_name"), str
    ):
        raise EvidenceError("event")
    item = event.get("workflow_run")
    if (
        repository["full_name"].casefold() != repo.casefold()
        or event.get("action") != "requested"
        or not isinstance(item, dict)
        or item.get("run_attempt") != 1
    ):
        return None
    identity = source.positive(item.get("id"))
    actual = source._api(f"repos/{repo}/actions/runs/{identity}")
    if not source.trusted_run(actual, repo):
        return None
    if actual["id"] != identity:
        raise EvidenceError("protocol")
    sha = actual["head_sha"]
    prs = actual["pull_requests"] or source.records(f"repos/{repo}/commits/{sha}/pulls")
    numbers = sorted({source.positive(pr.get("number")) for pr in prs})
    eligible = [number for number in numbers if _open(repo, number, sha)]
    if len(eligible) != 1:
        return None
    return {"number": eligible[0], "sha": sha, "run_id": None}


def missing(repo: str, number: int, sha: str) -> dict[str, bool]:
    """Kinds absent on this head: a posted kind is never reviewed twice."""
    rows = source.records(f"repos/{repo}/pulls/{number}/reviews")
    result = claude.review_evidence(rows, sha, True)
    if result["reason"] in ("protocol", "arguments"):
        raise EvidenceError("protocol")
    return {kind: result[kind]["state"] == "pending" for kind in claude.KINDS}


def targets(event: Record, repo: str) -> dict[str, str]:
    trigger = target(event, repo)
    if trigger is None:
        return dict(EMPTY)
    kinds = missing(repo, trigger["number"], trigger["sha"])
    values = {"pr": str(trigger["number"]), "sha": trigger["sha"]}
    values.update({kind: str(kinds[kind]).lower() for kind in claude.KINDS})
    return values


def resume(event: Record, repo: str) -> Record:
    trigger = target(event, repo)
    return NONE.copy() if trigger is None else codex_event.resume(repo, trigger)


def _output(values: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise EvidenceError("output")
    try:
        with Path(path).open("a", encoding="utf-8") as output:
            output.write("".join(f"{key}={values[key]}\n" for key in EMPTY))
    except OSError as exc:
        raise EvidenceError("output") from exc


def _event(repo: str) -> Record:
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
    return event


def main(argv: list[str] | None = None) -> int:
    try:
        flags = sys.argv[1:] if argv is None else argv
        if flags not in ([], ["--target"]):
            raise EvidenceError("arguments")
        targeting = bool(flags)
        if os.environ.get("GITHUB_EVENT_NAME", "") != EVENT:
            if targeting:
                _output(EMPTY)
            print(json.dumps(EMPTY if targeting else NONE, sort_keys=True))
            return 0
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        event = _event(repo)
        if targeting:
            result: Any = targets(event, repo)
            _output(result)
        else:
            result = resume(event, repo)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, UnicodeError):
        print("claude review event: event", file=sys.stderr)
        return 1
    except EvidenceError as exc:
        print(f"claude review event: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
