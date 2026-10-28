"""Reject event routes that expose PR review to the privileged merge workflow.

Source: zetetic-team-subagents PR189 separated-events design (2026-10-24).
These literal contracts target its generated YAML, not arbitrary YAML syntax.
"""

from __future__ import annotations

import re

# Source: the accepted direct, reusable and caller trigger contracts.
DIRECT_EVENTS = (
    "pull_request: types: [opened, synchronize, reopened, ready_for_review] "
    "push: branches: [main]"
)
ENGINE_EVENTS = "workflow_call: secrets: RELEASE_TAG_SSH_KEY: required: false"
CALLER_EVENTS = (
    "workflow_run: workflows: [Pipeline] types: [completed] branches-ignore: [main]"
)
CALLER_CONDITION = (
    "github.event.workflow_run.event == 'pull_request' "
    "&& github.event.workflow_run.conclusion == 'success'"
)


def _header(text, field, key):
    prefix = text.split("\njobs:", 1)[0]
    return field(["    " + line for line in prefix.splitlines()], key)


def _caller(text, bodies, field):
    jobs = bodies(text)
    if set(jobs) != {"pipeline"}:
        return ["after-merge caller must contain only its pipeline call"]
    job = jobs["pipeline"]
    expected = {
        "uses": "./.github/workflows/pipeline-post-merge.yml",
        "if": CALLER_CONDITION,
        "permissions": "contents: write pull-requests: write actions: read",
        "secrets": "RELEASE_TAG_SSH_KEY: ${{ secrets.RELEASE_TAG_SSH_KEY }}",
        "steps": "",
        "needs": "",
    }
    failures = [
        f"after-merge caller has unsafe {name}"
        for name, value in expected.items()
        if field(job, name) != value
    ]
    if field(job, "continue-on-error") not in ("", "false"):
        failures.append("after-merge caller must not ignore failures")
    return failures


def check_profile_route(text, post_merge, bodies, field):
    """The profile is supplied by the caller, never discovered from YAML."""
    name = "Pipeline post-merge tests" if post_merge else "Pipeline"
    events = ENGINE_EVENTS if post_merge else DIRECT_EVENTS
    failures = []
    if _header(text, field, "name") != name:
        failures.append(f"{name} must retain its workflow receipt name")
    if _header(text, field, "on") != events:
        failures.append(f"{name} has unsafe event routing")
    if any(field(job, "uses") for job in bodies(text).values()):
        failures.append("Pipeline engines must execute their jobs directly")
    if post_merge and re.search(r"(?im)^\s*(?:-\s*)?uses:\s*.*claude", text):
        failures.append("post-merge engine cannot execute a Claude action")
    return failures


def check_routes(workflows, bodies, field):
    """Check all three files together, including the only permitted local call."""
    direct, engine, caller = workflows
    failures = []
    try:
        failures += check_profile_route(direct, False, bodies, field)
        failures += check_profile_route(engine, True, bodies, field)
        if _header(caller, field, "name") != "Pipeline after merge":
            failures.append("after-merge caller must retain its receipt name")
        if _header(caller, field, "on") != CALLER_EVENTS:
            failures.append("after-merge caller has unsafe event routing")
        return failures + _caller(caller, bodies, field)
    except ValueError as error:
        return [str(error)]
