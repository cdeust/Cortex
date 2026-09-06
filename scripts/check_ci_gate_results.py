"""Fail CI Green unless every job succeeded or has a verified skip reason.

The policy mirrors ci.yml: code, dependency or workflow PR changes run code
jobs and Docker smoke. Pushes and dispatches also run those jobs; schedules
run smoke but skip code jobs. Runtime/devcontainer builds require Docker
changes, a schedule or a dispatch. The vendor CLI job skips fork PRs because
it executes npm postinstall. Missing classifications and unknown jobs fail closed.

Source: tasks/codex-green-remediation-plan.md W1-2/W1-4 and ci.yml predicates.
GitHub's needs context exposes result and outputs for direct dependencies:
https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#needs-context
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# source: .github/workflows/ci.yml, jobs gated by changes and lint.
CODE_JOBS = frozenset(
    {
        "test",
        "test-sqlite",
        "mcp-host-config",
        "test-windows",
        "release-deps",
        "craftsmanship",
        "typecheck",
        "build",
    }
)
DOCKER_BUILD_JOBS = frozenset({"docker-runtime-build", "devcontainer-build"})
ALWAYS_JOBS = frozenset({"changes", "lint"})
CONDITIONAL_JOBS = CODE_JOBS | DOCKER_BUILD_JOBS | {"docker-smoke"}
EXPECTED_JOBS = ALWAYS_JOBS | CONDITIONAL_JOBS
# source: .github/workflows/ci.yml changes.outputs and on triggers.
FILTERS = frozenset({"code", "docs", "docker", "workflows", "deps"})
EVENTS = frozenset({"pull_request", "push", "workflow_dispatch", "schedule"})


def check_policy(needs: list[str], allowed: list[str]) -> list[str]:
    """Keep the workflow and the executable skip policy in exact agreement."""
    failures = []
    if set(needs) != EXPECTED_JOBS:
        failures.append("CI Green needs do not match the runtime job policy")
    if set(allowed) != CONDITIONAL_JOBS:
        failures.append("ALLOWED_SKIPS does not match the runtime skip policy")
    return failures


def _classifications(needs: dict) -> dict[str, bool]:
    outputs = needs["changes"].get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != FILTERS:
        raise ValueError("changes must provide exactly the five path outputs")
    if any(value not in ("true", "false") for value in outputs.values()):
        raise ValueError("changes outputs must be the strings 'true' or 'false'")
    return {name: value == "true" for name, value in outputs.items()}


def _is_fork(event_name: str, event: dict) -> bool:
    if event_name != "pull_request":
        return False
    try:
        fork = event["pull_request"]["head"]["repo"]["fork"]
    except (KeyError, TypeError) as error:
        raise ValueError("pull_request event is missing head.repo.fork") from error
    if not isinstance(fork, bool):
        raise ValueError("pull_request head.repo.fork must be a boolean")
    return fork


def _required_jobs(flags: dict[str, bool], event_name: str, fork: bool) -> set[str]:
    full = event_name != "pull_request" or any(
        flags[name] for name in ("code", "deps", "workflows")
    )
    required = set(ALWAYS_JOBS)
    if full and event_name != "schedule":
        required.update(CODE_JOBS)
    if full or flags["docker"]:
        required.add("docker-smoke")
    if flags["docker"] or event_name in ("schedule", "workflow_dispatch"):
        required.update(DOCKER_BUILD_JOBS)
    if fork:
        required.discard("mcp-host-config")
    return required


def check(needs: dict, event_name: str, event: dict) -> list[str]:
    """Evaluate actual results, never treating an allowlist as a skip reason."""
    if not isinstance(needs, dict) or set(needs) != EXPECTED_JOBS:
        return ["needs must contain exactly the expected CI jobs"]
    if event_name not in EVENTS or not isinstance(event, dict):
        return ["missing or unsupported GitHub event context"]
    if any(not isinstance(value, dict) for value in needs.values()):
        return ["every needs entry must be a job result object"]
    try:
        flags = _classifications(needs)
        required = _required_jobs(flags, event_name, _is_fork(event_name, event))
    except ValueError as error:
        return [str(error)]
    failures = []
    for job, value in sorted(needs.items()):
        result = value.get("result")
        if result == "success":
            continue
        if result == "skipped" and job not in required:
            continue
        failures.append(f"{job}={result!r} (success required or invalid result)")
    return failures


def main() -> int:
    try:
        allowed = os.environ["ALLOWED_SKIPS"].split(",")
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        needs = json.loads(os.environ["NEEDS"])
        failures = check(needs, os.environ["GITHUB_EVENT_NAME"], event)
        if set(allowed) != CONDITIONAL_JOBS:
            failures.append("ALLOWED_SKIPS does not match the runtime skip policy")
    except (KeyError, OSError, ValueError) as error:
        failures = [f"cannot read CI gate inputs: {error}"]
    if failures:
        for failure in failures:
            print(f"::error::CI Green: {failure}", file=sys.stderr)
        return 1
    print("CI Green: all required jobs succeeded; every skip is justified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
