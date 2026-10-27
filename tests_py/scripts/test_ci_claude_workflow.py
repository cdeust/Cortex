"""Contracts of .github/workflows/claude.yml (ADR-1116).

Sources: GitHub events reference (workflow_run runs the default-branch file;
pull_request_review runs refs/pull/N/merge) and anthropics/claude-code-action
v1.0.263 action.yml (App token revoked after the step).
"""

from __future__ import annotations

import re
import unittest

from tests_py.scripts.test_ci_claude_wiring import CLAUDE_YML, CODEX_YML, PIN, job


class ClaudeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = CLAUDE_YML.read_text()

    def test_every_action_use_is_the_verified_pin_without_token_override(self):
        uses = re.findall(r"uses: anthropics/claude-code-action@[^\n]*", self.text)
        self.assertGreaterEqual(len(uses), 3)
        self.assertEqual(set(uses), {"uses: " + PIN})
        self.assertNotIn("github_token:", self.text)
        self.assertNotIn('allowed_bots: "*"', self.text)
        self.assertNotIn("allowed_non_write_users", self.text)

    def test_triggers_run_only_default_branch_definitions(self):
        on = self.text.split("\non:\n", 1)[1].split("\nenv:\n", 1)[0]
        self.assertIn("workflows: [Pipeline]", on)
        self.assertIn("types: [requested]", on)
        for event in ("pull_request_review", "pull_request_target", "pull_request:"):
            self.assertNotIn(event, on)

    def test_only_resume_holds_actions_write_and_reviews_cannot_write(self):
        self.assertEqual(self.text.count("actions: write"), 1)
        self.assertIn("actions: write", job(self.text, "resume"))
        for name in ("target", "review", "verify"):
            with self.subTest(job=name):
                body = job(self.text, name)
                self.assertNotIn(": write\n", body.replace("id-token: write\n", ""))
        self.assertIn("id-token: write", job(self.text, "review"))
        self.assertNotIn("id-token", job(self.text, "resume"))

    def test_review_jobs_check_out_main_only_and_never_the_pr_head(self):
        for name in ("target", "review", "verify", "resume"):
            with self.subTest(job=name):
                body = job(self.text, name)
                self.assertIn("ref: main", body)
                self.assertIn("persist-credentials: false", body)
                forbidden = r"head\.ref|head_branch|refs/pull|download-artifact"
                self.assertIsNone(re.search(forbidden, body))

    def test_review_runs_once_per_pipeline_run_and_publishes_exact_head(self):
        target = job(self.text, "target")
        self.assertIn("github.event.workflow_run.run_attempt == 1", target)
        review = job(self.text, "review")
        self.assertIn("cancel-in-progress: true", review)
        self.assertIn(
            'allowed_bots: "claude[bot],chatgpt-codex-connector[bot],dependabot[bot]"',
            review,
        )
        self.assertNotIn("Bash(gh api:*)", review)
        repo, pr, sha = (
            "${{ github.repository }}",
            "${{ env.PR }}",
            "${{ env.HEAD_SHA }}",
        )
        temp = "${{ runner.temp }}"
        for kind in ("code", "security"):
            exact = (
                f"Bash(gh api -X POST repos/{repo}/pulls/{pr}/reviews"
                f" -f commit_id={sha} -f event=COMMENT"
                f" -F body=@{temp}/claude-review/{kind}-review.md)"
            )
            # The App token has contents:write: only this exact write is allowed.
            self.assertIn(exact, review)
            self.assertEqual(review.count("Bash(gh api"), 2)
            self.assertIn(f"Edit(/{temp}/claude-review/{kind}-review.md)", review)
            self.assertNotIn(",Write,", review)
            self.assertIn("steps.kinds.outputs." + kind + " == 'true'", review)
            self.assertIn(f"<!-- claude-review:v1 kind={kind} findings=N -->", review)

    def test_verification_is_a_separate_untouched_job(self):
        verify = job(self.text, "verify")
        self.assertIn("python3 -I scripts/ci_claude_reviews.py", verify)
        self.assertIn("--assume-required --require-complete", verify)
        resume = job(self.text, "resume")
        self.assertIn("python3 -B scripts/ci_claude_review_event.py", resume)
        self.assertNotIn("needs.review.outputs", resume)

    def test_resume_serialises_with_the_codex_completion_handler(self):
        group = "codex-review-completion-${{ github.repository }}-"
        codex = CODEX_YML.read_text()
        self.assertIn(group + "${{ needs.identify.outputs.pr }}", codex)
        self.assertIn(
            group + "${{ needs.target.outputs.pr }}", job(self.text, "resume")
        )
        self.assertIn("cancel-in-progress: false", job(self.text, "resume"))

    def test_tag_job_never_answers_claude_itself(self):
        tag = job(self.text, "claude")
        self.assertIn("github.event.comment.user.login != 'claude[bot]'", tag)
        self.assertIn("github.event.comment.user.type != 'Bot'", tag)


if __name__ == "__main__":
    unittest.main()
