# source: https://github.com/cdeust/Cortex/blob/f4831d159c181b5e170c984f703ed733819f188e/tests_py/scripts/test_ci_codex_review_event_fixtures.py
"""GitHub REST fixtures: Pipeline run/job identities and native Codex summaries."""

from __future__ import annotations

import copy
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

from codex_resume_fixtures import (
    SHA,
    BOT_NODE_ID,
    comment,
    pull,
    summary_pages,
    with_claude,
)
from test_ci_codex_review_resume import jobs

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci_codex_review_event.py"
REPO = "cdeust/Cortex"
PREFIX = "repos/" + REPO
BOT = {
    "login": "chatgpt-codex-connector[bot]",
    "type": "Bot",
    "node_id": BOT_NODE_ID,
}
RUNS = (
    PREFIX + "/actions/workflows/pipeline.yml/runs?event=pull_request&head_sha=" + SHA
)
DETAIL = PREFIX + "/actions/runs/50"
JOBS = DETAIL + "/attempts/1/jobs"
PULL = PREFIX + "/pulls/797"
COMMENTS = "graphql"


def source():
    return {
        "id": 50,
        "run_number": 100,
        "run_attempt": 1,
        "name": "Pipeline",
        "path": ".github/workflows/pipeline.yml",
        "event": "pull_request",
        "head_sha": SHA,
        "head_branch": "fix/security",
        "status": "completed",
        "conclusion": "failure",
        "repository": {"full_name": REPO, "id": 42},
        "head_repository": {"full_name": REPO, "id": 42},
        "pull_requests": [
            {
                "number": 797,
                "head": {"ref": "fix/security", "sha": SHA, "repo": {"id": 42}},
                "base": {"ref": "main", "repo": {"id": 42}},
            }
        ],
    }


def event(name="issue_comment"):
    value = {"repository": {"full_name": REPO}, "sender": copy.deepcopy(BOT)}
    if name == "issue_comment":
        value.update(
            action="edited",
            issue={"number": 797, "pull_request": {}},
            comment={
                "id": 9,
                "user": copy.deepcopy(BOT),
                "body": "<!-- codex-pull-request-review-summary -->",
            },
        )
    elif name == "pull_request_review":
        value.update(
            action="submitted",
            pull_request={"number": 797},
            review={"id": 3, "user": copy.deepcopy(BOT)},
        )
    else:
        value.update(action="completed", workflow_run={"id": 50})
    return value


def load():
    spec = importlib.util.spec_from_file_location("codex_event", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class Server:
    def __init__(self):
        pr = pull()
        pr["head"].update(ref="fix/security")
        pr["head"]["repo"]["id"] = 42
        pr["base"]["repo"]["id"] = 42
        pr.update(title="Fix security", labels=[])
        proof = comment(comment_id=9)
        proof["issue_url"] = "https://api.github.com/" + PREFIX + "/issues/797"
        current_jobs = jobs()
        for job in current_jobs:
            job.update(run_id=50, run_attempt=1, head_sha=SHA)
        self.data = {
            "pull": pr,
            "source": source(),
            "jobs": current_jobs,
            "comments": [proof],
            "comment": proof,
            "review": {
                "id": 3,
                "user": copy.deepcopy(BOT),
                "commit_id": SHA,
                "pull_request_url": "https://api.github.com/" + PULL,
            },
        }
        self.calls = []
        self.overrides = {}

    def __call__(self, endpoint, *, paginate=False, fields=None):
        self.calls.append((endpoint, paginate))
        count = sum(path == endpoint for path, _ in self.calls)
        if endpoint in self.overrides:
            return copy.deepcopy(self.overrides[endpoint](count))
        if endpoint == PULL:
            result = self.data["pull"]
        elif endpoint == PREFIX + "/issues/comments/9":
            result = self.data["comment"]
        elif endpoint == PULL + "/reviews/3":
            result = self.data["review"]
        elif endpoint == COMMENTS:
            result = self.graphql(fields)
        elif endpoint == RUNS:
            result = [{"total_count": 1, "workflow_runs": [self.data["source"]]}]
        elif endpoint == DETAIL:
            result = self.data["source"]
        elif endpoint == JOBS:
            result = [
                {"total_count": len(self.data["jobs"]), "jobs": self.data["jobs"]}
            ]
        elif endpoint == PREFIX + "/commits/" + SHA + "/pulls":
            result = [[self.data["pull"]]]
        elif endpoint == PREFIX + "/commits/" + SHA[:10]:
            result = {"sha": SHA}  # a security receipt's prefix, resolved (#227)
        else:
            raise AssertionError("unexpected API endpoint: " + endpoint)
        return copy.deepcopy(result)

    def graphql(self, fields):
        if not fields:
            raise AssertionError("unexpected GraphQL query")
        if "reviewThreads(" in fields["query"]:
            return [self.data["threads"]]
        sha = self.data["pull"]["head"]["sha"]
        rows = self.data["comments"]
        if self.data.get("claude", True):
            rows = with_claude(rows, sha)
        return summary_pages([rows], number=fields["number"], sha=sha)


def invoke(server, name="issue_comment", payload=None, expected=797):
    target = load()
    runtime = sys.modules["ci_codex_review_runtime"]
    with (
        patch.dict(os.environ, {"EXPECTED_PR": str(expected)}),
        patch.object(target.source, "_api", side_effect=server),
        patch.object(runtime, "_api", side_effect=server),
        patch.object(target.subprocess, "run") as post,
    ):
        result = target.coordinate(
            name, event(name) if payload is None else payload, REPO
        )
    return result, post.call_args_list


def invoke_resume(server, trigger):
    target = load()
    runtime = sys.modules["ci_codex_review_runtime"]
    with (
        patch.dict(os.environ, {"EXPECTED_PR": "797"}),
        patch.object(target.source, "_api", side_effect=server),
        patch.object(runtime, "_api", side_effect=server),
        patch.object(target.subprocess, "run") as post,
    ):
        result = target.resume(REPO, trigger)
    return result, post.call_args_list
