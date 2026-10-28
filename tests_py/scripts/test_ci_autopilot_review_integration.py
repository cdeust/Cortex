"""Local review reconciliation uses real current-head readers and resume policy."""

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from ci_autopilot_review import check
import ci_codex_reviews as reader
from tests_py.scripts.test_ci_codex_review_event_fixtures import REPO, SHA, Server, load


class TrustedReviewIntegration(unittest.TestCase):
    def invoke(self, server):
        target = load()
        args = SimpleNamespace(repo=REPO, pr=797, sha=SHA)
        # source: test_ci_codex_review_event_fixtures binds PR797 and jobs20/21.
        with (
            patch.dict(os.environ, {"EXPECTED_PR": "797"}),
            patch.object(target.source, "_api", side_effect=server),
            patch.object(reader, "_api", side_effect=server),
            patch.object(target.subprocess, "run") as post,
        ):
            result = check(args, target, reader)
        return result, post.call_args_list

    def test_actual_clean_reader_and_job_policy_rerun_only_waiting_merge_job(self):
        result, posts = self.invoke(Server())
        self.assertEqual(result, {"action": "merge", "job_id": 21})
        self.assertEqual(
            posts[0].args[0],
            [
                "gh",
                "api",
                "--method",
                "POST",
                "repos/cdeust/Cortex/actions/jobs/21/rerun",
            ],
        )
        self.assertEqual(len(posts), 1)

    def test_human_edited_original_bot_summary_never_reruns_or_repairs(self):
        server = Server()
        summary = server.data["comments"][0]
        summary.update(
            editor={"login": "collaborator", "__typename": "User", "id": "U_other"},
            lastEditedAt="2026-10-28T00:00:00Z",
        )
        result, posts = self.invoke(server)
        self.assertEqual(result, {"action": "none", "reason": "evidence_unverifiable"})
        self.assertEqual(posts, [])

    def test_pending_workflow_attempt_is_not_rerun_even_after_clean_review(self):
        server = Server()
        server.data["source"].update(status="in_progress", conclusion=None)
        result, posts = self.invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(posts, [])

    def test_unrelated_review_toolchain_failure_enters_repair_without_rerun(self):
        server = Server()
        review = next(job for job in server.data["jobs"] if job["name"] == "review")
        review.update(
            conclusion="failure",
            steps=[{"name": "Initialize review toolchain", "conclusion": "failure"}],
        )
        result, posts = self.invoke(server)
        self.assertEqual(
            result, {"action": "repair", "reason": "review_infrastructure"}
        )
        self.assertEqual(posts, [])

    def test_exact_readiness_failure_reuses_native_policy_without_repair(self):
        from ci_codex_review_resume import READINESS

        server = Server()
        review = next(job for job in server.data["jobs"] if job["name"] == "review")
        review.update(
            conclusion="failure",
            steps=[{"name": READINESS[0], "conclusion": "failure"}],
        )
        result, posts = self.invoke(server)
        self.assertEqual(result, {"action": "review", "job_id": review["id"]})
        self.assertEqual(len(posts), 1)

    def test_unrelated_build_failure_never_enters_review_infrastructure_repair(self):
        server = Server()
        for name in ("unit", "review"):
            job = next(job for job in server.data["jobs"] if job["name"] == name)
            job.update(
                conclusion="failure",
                steps=[{"name": "Initialize toolchain", "conclusion": "failure"}],
            )
        result, posts = self.invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(posts, [])

    def test_absent_native_completion_never_enters_infrastructure_repair(self):
        server = Server()
        server.data["comments"] = []
        review = next(job for job in server.data["jobs"] if job["name"] == "review")
        review.update(
            conclusion="failure",
            steps=[{"name": "Initialize toolchain", "conclusion": "failure"}],
        )
        result, posts = self.invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(posts, [])

    def test_current_findings_do_not_launch_repair_during_a_running_workflow(self):
        from tests_py.scripts.test_ci_codex_reviews import comment, state

        server = Server()
        data = state()
        data["code_review"].update(has_any_findings=True, has_unresolved_findings=True)
        server.data["comments"] = [comment(data)]
        server.data["source"].update(status="in_progress", conclusion=None)
        result, posts = self.invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(posts, [])
