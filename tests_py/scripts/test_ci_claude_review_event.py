"""Only authenticated exact-head claude[bot] reviews may resume the waiting gate.

One test per invariant of scripts/ci_claude_review_event.py and of the shared
Codex coordinator once main's claude.yml declares CLAUDE_REVIEW_GATE: required.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests_py.scripts.test_ci_claude_reviews import OTHER, clean, review, workflow
from tests_py.scripts.test_ci_codex_review_event_fixtures import (
    PREFIX,
    REPO,
    REVIEWS,
    SHA,
    Server,
)

ROOT = Path(__file__).resolve().parents[2]
CLAUDE = ROOT / "scripts/ci_claude_review_event.py"
CODEX = ROOT / "scripts/ci_codex_review_event.py"
RERUN_REVIEW = ["gh", "api", "--method", "POST", PREFIX + "/actions/jobs/20/rerun"]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def requested(attempt=1, repo=REPO, action="requested"):
    return {
        "action": action,
        "repository": {"full_name": repo},
        "workflow_run": {"id": 50, "run_attempt": attempt},
    }


def gate(server, mode="required"):
    server.data["workflows"].append({"name": "claude.yml", "type": "file"})
    server.data["claude_yml"] = workflow(mode)
    return server


def waiting(server):
    """Pipeline green while the merge job waits under 'merge pending review'."""
    server.data["source"]["conclusion"] = "success"
    server.data["jobs"][-1].update(
        name="merge pending review", conclusion="success", steps=[]
    )
    return server


def call(server, function, *args, expected=797):
    target = load(CLAUDE, "claude_event")
    with (
        patch.dict(os.environ, {"EXPECTED_PR": str(expected)}),
        patch.object(target.source, "_api", side_effect=server),
        patch.object(target.codex_event.subprocess, "run") as post,
    ):
        result = getattr(target, function)(*args)
    return result, post.call_args_list


class TargetTests(unittest.TestCase):
    def test_requested_run_names_live_pr_and_missing_kinds(self):
        server = Server()
        server.data["source"].update(status="queued", conclusion=None)
        result, _ = call(server, "targets", requested(), REPO)
        self.assertEqual(
            result, {"pr": "797", "sha": SHA, "code": "true", "security": "true"}
        )
        server.data["reviews"] = [review("code", 0, 1)]
        result, _ = call(server, "targets", requested(), REPO)
        self.assertEqual((result["code"], result["security"]), ("false", "true"))

    def test_rerun_attempts_and_foreign_events_never_target(self):
        for payload in (
            requested(attempt=2),
            requested(action="completed"),
            requested(repo="other/repo"),
        ):
            with self.subTest(payload=payload):
                server = Server()
                result, _ = call(server, "targets", payload, REPO)
                self.assertEqual(result["pr"], "")
                self.assertEqual(server.calls, [])

    def test_untrusted_run_identity_never_targets(self):
        for field, value in (
            ("head_repository", {"full_name": "fork/Cortex", "id": 7}),
            ("event", "push"),
            ("name", "Other"),
            ("path", ".github/workflows/other.yml"),
        ):
            with self.subTest(field=field):
                server = Server()
                server.data["source"][field] = value
                result, _ = call(server, "targets", requested(), REPO)
                self.assertEqual(result["pr"], "")

    def test_moved_draft_closed_or_cross_repo_pr_never_targets(self):
        for mutate in (
            lambda pull: pull["head"].update(sha=OTHER),
            lambda pull: pull.update(draft=True),
            lambda pull: pull.update(state="closed"),
            lambda pull: pull["head"]["repo"].update(full_name="fork/Cortex"),
        ):
            server = Server()
            mutate(server.data["pull"])
            result, _ = call(server, "targets", requested(), REPO)
            self.assertEqual(result["pr"], "")

    def test_empty_run_association_resolves_from_head_sha(self):
        server = Server()
        server.data["source"]["pull_requests"] = []
        result, _ = call(server, "targets", requested(), REPO)
        self.assertEqual(result["pr"], "797")
        self.assertIn((PREFIX + "/commits/" + SHA + "/pulls", True), server.calls)


class ResumeTests(unittest.TestCase):
    def test_complete_sources_rerun_only_the_review_job(self):
        server = waiting(gate(Server()))
        server.data["reviews"] = clean()
        result, post = call(server, "resume", requested(), REPO)
        self.assertEqual(result, {"action": "review", "job_id": 20})
        self.assertEqual([item.args[0] for item in post], [RERUN_REVIEW])

    def test_pending_claude_review_never_resumes(self):
        server = waiting(gate(Server()))
        result, post = call(server, "resume", requested(), REPO)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_review_on_another_head_or_by_non_bot_never_resumes(self):
        for rows in (
            [
                review("code", commit_id=OTHER),
                review("security", 0, 2, commit_id=OTHER),
            ],
            [
                review("code", user={"login": "claude[bot]", "type": "User"}),
                review("security", 0, 2, user={"login": "cdeust", "type": "User"}),
            ],
            [
                review("code", user={"login": "github-actions[bot]", "type": "Bot"}),
                review("security", 0, 2),
            ],
        ):
            server = waiting(gate(Server()))
            server.data["reviews"] = rows
            result, post = call(server, "resume", requested(), REPO)
            self.assertEqual(result, {"action": "none"})
            self.assertEqual(post, [])

    def test_expected_pr_mismatch_or_cross_repo_pr_never_resumes(self):
        server = waiting(gate(Server()))
        server.data["reviews"] = clean()
        result, post = call(server, "resume", requested(), REPO, expected=798)
        self.assertEqual((result, post), ({"action": "none"}, []))
        server.data["pull"]["head"]["repo"]["full_name"] = "fork/Cortex"
        result, post = call(server, "resume", requested(), REPO)
        self.assertEqual((result, post), ({"action": "none"}, []))

    def test_merge_blocked_on_claude_step_resumes_only_when_clean(self):
        for findings, expected in ((0, {"action": "merge", "job_id": 21}), (1, None)):
            server = gate(Server())
            server.data["jobs"][-1]["steps"] = [
                {"name": "Require complete Claude reviews", "conclusion": "failure"}
            ]
            server.data["reviews"] = [
                review("code", findings, 1),
                review("security", 0, 2),
            ]
            result, post = call(server, "resume", requested(), REPO)
            self.assertEqual(result, expected or {"action": "none"})
            self.assertEqual(len(post), 1 if expected else 0)


class CodexCoordinatorTests(unittest.TestCase):
    """The Codex Pipeline-completed catch shares the combined proof."""

    def coordinate(self, server):
        target = load(CODEX, "codex_event_with_claude")
        with (
            patch.dict(os.environ, {"EXPECTED_PR": "797"}),
            patch.object(target.source, "_api", side_effect=server),
            patch.object(target.subprocess, "run") as post,
        ):
            payload = {
                "repository": {"full_name": REPO},
                "action": "completed",
                "workflow_run": {"id": 50},
            }
            result = target.coordinate("workflow_run", payload, REPO)
        return result, post.call_args_list

    def test_codex_completion_waits_for_required_claude_review(self):
        # Without the combined proof, a green waiting Pipeline is rerun forever:
        # each rerun completes as 'merge pending review' and fires this catch again.
        result, post = self.coordinate(waiting(gate(Server())))
        self.assertEqual((result, post), ({"action": "none"}, []))

    def test_observe_gate_keeps_codex_only_resumption(self):
        for server in (waiting(Server()), waiting(gate(Server(), "observe"))):
            result, post = self.coordinate(server)
            self.assertEqual(result, {"action": "review", "job_id": 20})
            self.assertEqual(len(post), 1)
            self.assertNotIn((REVIEWS, True), server.calls)

    def test_required_gate_with_complete_reviews_resumes(self):
        server = waiting(gate(Server()))
        server.data["reviews"] = clean()
        result, post = self.coordinate(server)
        self.assertEqual(result, {"action": "review", "job_id": 20})
        self.assertEqual(len(post), 1)


class CommandLineTests(unittest.TestCase):
    def test_other_events_write_empty_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            env = dict(os.environ, GITHUB_EVENT_NAME="issue_comment")
            env["GITHUB_OUTPUT"] = str(output)
            for flags in (["--target"], []):
                done = subprocess.run(
                    [sys.executable, str(CLAUDE), *flags],
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(
                output.read_text(), "pr=\nsha=\ncode=false\nsecurity=false\n"
            )

    def test_unknown_arguments_fail(self):
        done = subprocess.run(
            [sys.executable, str(CLAUDE), "--publish"], text=True, capture_output=True
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("arguments", done.stderr)


if __name__ == "__main__":
    unittest.main()
