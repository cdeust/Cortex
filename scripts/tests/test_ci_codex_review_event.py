# source: https://github.com/cdeust/Cortex/blob/f4831d159c181b5e170c984f703ed733819f188e/tests_py/scripts/test_ci_codex_review_event.py
"""Only authenticated current-head completion may resume the exact waiting job."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import unittest

from test_ci_codex_review_event_fixtures import (
    COMMENTS,
    DETAIL,
    JOBS,
    PREFIX,
    PULL,
    RUNS,
    SCRIPT,
    SHA,
    Server,
    event,
    invoke,
)
from codex_resume_fixtures import OTHER, state, comment, summary_pages
from test_ci_codex_review_resume import waiting_jobs


class CodexEventTests(unittest.TestCase):
    def test_completed_review_resumes_successful_waiting_pipeline(self):
        for name in ("issue_comment", "workflow_run"):
            server = Server()
            server.data["source"]["conclusion"] = "success"
            server.data["jobs"][-1].update(
                name="merge pending review", conclusion="success", steps=[]
            )
            result, post = invoke(server, name)
            self.assertEqual(result, {"action": "review", "job_id": 20})
            self.assertEqual(len(post), 1)

    def test_unknown_cli_event_does_nothing(self):
        env = dict(os.environ)
        env["GITHUB_EVENT_NAME"] = "push"
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], env=env, text=True, capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '{"action": "none"}')

    def test_current_clean_completion_reruns_exact_merge_job(self):
        server = Server()
        result, post = invoke(server)
        self.assertEqual(result, {"action": "merge", "job_id": 21})
        self.assertEqual(
            post[0].args[0],
            ["gh", "api", "--method", "POST", PREFIX + "/actions/jobs/21/rerun"],
        )
        self.assertFalse(post[0].kwargs.get("shell", False))

    def test_complete_findings_resume_waiting_review(self):
        server = Server()
        server.data["jobs"] = waiting_jobs()
        for job in server.data["jobs"]:
            job.update(run_id=50, run_attempt=1, head_sha=SHA)
        data = state()
        data["code_review"].update(has_any_findings=True, has_unresolved_findings=True)
        server.data["comments"] = [comment(data)]
        result, post = invoke(server)
        self.assertEqual(result, {"action": "review", "job_id": 20})
        self.assertEqual(len(post), 1)

    def test_forged_event_actor_is_ignored_before_api(self):
        for key in ("sender", "comment"):
            server = Server()
            payload = event()
            if key == "sender":
                payload[key]["type"] = "User"
            else:
                payload[key]["user"]["login"] = "other[bot]"
            result, post = invoke(server, payload=payload)
            self.assertEqual(result, {"action": "none"})
            self.assertEqual(post, [])
            self.assertEqual(server.calls, [])

    def test_server_rereads_comment_author_and_pr_binding(self):
        for field, value in (
            ("user", {"login": "cdeust", "type": "User"}),
            ("issue_url", "https://api.github.com/repos/other/repo/issues/797"),
        ):
            server = Server()
            server.data["comment"][field] = value
            result, post = invoke(server)
            self.assertEqual(result, {"action": "none"})
            self.assertEqual(post, [])

    def test_noncanonical_comment_and_non_pr_issue_are_ignored(self):
        for mutate in (
            lambda p: p["comment"].update(body="hello"),
            lambda p: p["issue"].pop("pull_request"),
        ):
            server = Server()
            payload = event()
            mutate(payload)
            result, post = invoke(server, payload=payload)
            self.assertEqual(result, {"action": "none"})
            self.assertEqual(post, [])

    def test_pr_review_event_is_ignored_because_workflow_definition_is_untrusted(self):
        server = Server()
        result, post = invoke(server, "pull_request_review")
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])
        self.assertEqual(server.calls, [])

    def test_empty_run_association_can_identify_but_cannot_mutate(self):
        from test_ci_codex_review_event_fixtures import load
        from unittest.mock import patch

        server = Server()
        server.data["source"]["pull_requests"] = []
        target = load()
        with patch.object(target.source, "_api", side_effect=server):
            self.assertEqual(
                target.identify("workflow_run", event("workflow_run"), "cdeust/Cortex"),
                797,
            )
        result, post = invoke(server, "workflow_run")
        self.assertEqual(result["action"], "none")
        self.assertEqual(post, [])
        self.assertIn((PREFIX + "/commits/" + SHA + "/pulls", True), server.calls)

    def test_same_commit_in_another_pr_cannot_select_its_job(self):
        server = Server()
        server.data["source"]["head_branch"] = "fix/other"
        server.data["source"]["pull_requests"][0].update(number=798)
        server.data["source"]["pull_requests"][0]["head"]["ref"] = "fix/other"
        result, post = invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_expected_pr_mismatch_cannot_mutate_under_another_concurrency_group(self):
        server = Server()
        result, post = invoke(server, expected=798)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_workflow_run_payload_claims_cannot_override_server_path_or_repo(self):
        for mutate in (
            lambda r: r.update(path=".github/workflows/evil.yml"),
            lambda r: r["repository"].update(full_name="other/repo"),
            lambda r: r["head_repository"].update(full_name="other/fork"),
            lambda r: r.update(event="pull_request_target"),
            lambda r: r.update(head_sha=OTHER),
        ):
            server = Server()
            mutate(server.data["source"])
            result, post = invoke(server, "workflow_run")
            self.assertEqual(result["action"], "none")
            self.assertEqual(post, [])

    def test_all_pr_holds_and_ineligible_states_prevent_rerun(self):
        for mutate in (
            lambda p: p.update(state="closed"),
            lambda p: p.update(draft=True),
            lambda p: p.update(title="DO NOT MERGE this"),
            lambda p: p.update(labels=[{"name": "Hold"}]),
            lambda p: p.update(labels=[{"name": "do-not-merge"}]),
            lambda p: p["head"]["repo"].update(full_name="other/fork"),
            lambda p: p["base"].update(ref="develop"),
        ):
            server = Server()
            mutate(server.data["pull"])
            result, post = invoke(server)
            self.assertEqual(result["action"], "none")
            self.assertEqual(post, [])

    def test_current_head_is_checked_immediately_before_post(self):
        server = Server()
        changed = copy.deepcopy(server.data["pull"])
        changed["head"]["sha"] = OTHER
        server.overrides[PULL] = lambda count: (
            server.data["pull"] if count == 1 else changed
        )
        result, post = invoke(server)
        self.assertEqual(result["action"], "none")
        self.assertEqual(post, [])

    def test_changed_attempt_or_running_status_cancels_old_plan(self):
        for change in (
            {"run_attempt": 2},
            {"status": "in_progress", "conclusion": None},
        ):
            server = Server()
            changed = copy.deepcopy(server.data["source"])
            changed.update(change)
            server.overrides[DETAIL] = (
                lambda count, original=server.data["source"], changed=changed: (
                    original if count == 1 else changed
                )
            )
            result, post = invoke(server)
            self.assertEqual(result["action"], "none")
            self.assertEqual(post, [])

    def test_changed_latest_run_cancels_old_plan(self):
        server = Server()
        new = copy.deepcopy(server.data["source"])
        new.update(id=51, run_number=101)
        server.overrides[RUNS] = lambda count: [
            {
                "total_count": 1,
                "workflow_runs": [server.data["source"] if count == 1 else new],
            }
        ]
        server.overrides[PREFIX + "/actions/runs/51"] = lambda count: new
        result, post = invoke(server)
        self.assertEqual(result["action"], "none")
        self.assertEqual(post, [])

    def test_job_failure_changes_are_recomputed_before_post(self):
        server = Server()
        changed = copy.deepcopy(server.data["jobs"])
        changed[0]["conclusion"] = "failure"
        server.overrides[JOBS] = lambda count: [
            {
                "total_count": len(changed),
                "jobs": server.data["jobs"] if count == 1 else changed,
            }
        ]
        result, post = invoke(server)
        self.assertEqual(result["action"], "none")
        self.assertEqual(post, [])

    def test_new_findings_before_post_cannot_resume_merge(self):
        server = Server()
        data = state()
        data["security_review"].update(
            has_any_findings=True, has_unresolved_findings=True
        )
        server.overrides[COMMENTS] = lambda count: summary_pages(
            [server.data["comments"] if count == 1 else [comment(data)]]
        )
        result, post = invoke(server)
        self.assertEqual(result["action"], "none")
        self.assertEqual(post, [])

    def test_unrelated_failure_cannot_be_retried(self):
        server = Server()
        server.data["jobs"].append(
            {
                "id": 99,
                "name": "other",
                "status": "completed",
                "conclusion": "failure",
                "run_id": 50,
                "run_attempt": 1,
                "head_sha": SHA,
            }
        )
        result, post = invoke(server)
        self.assertEqual(result["action"], "none")
        self.assertEqual(post, [])

    def test_wrong_job_run_attempt_or_head_is_protocol_failure(self):
        for key, value in (
            ("run_id", 51),
            ("run_attempt", 2),
            ("run_attempt", True),
            ("head_sha", OTHER),
        ):
            server = Server()
            server.data["jobs"][0][key] = value
            with self.assertRaisesRegex(ValueError, "protocol"):
                invoke(server)

    def test_partial_job_pagination_cannot_hide_an_unseen_failure(self):
        server = Server()
        server.overrides[JOBS] = lambda count: [
            {"total_count": len(server.data["jobs"]) + 1, "jobs": server.data["jobs"]}
        ]
        with self.assertRaisesRegex(ValueError, "protocol"):
            invoke(server)

    def test_malformed_pagination_or_identity_is_protocol_failure(self):
        for response in (
            {},
            [{"workflow_runs": "bad"}],
            [{"total_count": 1, "workflow_runs": [{"id": True, "run_number": 1}]}],
        ):
            server = Server()
            server.overrides[RUNS] = lambda count, response=response: response
            with self.assertRaisesRegex(ValueError, "protocol"):
                invoke(server)


if __name__ == "__main__":
    unittest.main()
