"""Regression guards for native Claude configuration, authority and edit mode."""

import shlex
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / ".github/workflows/claude-review.yml"
MENTIONS = ROOT / ".github/workflows/claude.yml"


class NativeClaudeTrustTests(unittest.TestCase):
    def test_automatic_review_can_read_and_publish_without_interactive_approval(self):
        # Upstream docs/solutions.md: Basic Example (No Tracking).
        workflow = yaml.safe_load(REVIEW.read_text())
        invocation = next(
            step
            for step in workflow["jobs"]["review"]["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        self.assertIn("Only post GitHub comments", invocation["with"]["prompt"])

    def test_automatic_review_uses_claude_app_identity(self):
        # Upstream issue396: github_token overrides the Claude App identity.
        workflow = yaml.safe_load(REVIEW.read_text())
        review = workflow["jobs"]["review"]
        invocation = next(
            step
            for step in review["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        self.assertNotIn("github_token", invocation["with"])
        self.assertEqual(
            review["permissions"],
            {"contents": "read", "pull-requests": "write", "id-token": "write"},
        )
        self.assertEqual(
            invocation["with"].get("claude_code_oauth_token"),
            "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
        )

    def test_owner_mentions_keep_app_authentication(self):
        workflow = yaml.safe_load(MENTIONS.read_text())
        mention = workflow["jobs"]["claude"]
        self.assertEqual(mention["permissions"]["id-token"], "write")
        invocation = next(
            step
            for step in mention["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        self.assertNotIn("github_token", invocation["with"])
        checkout = next(
            step
            for step in mention["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertFalse(checkout["with"]["persist-credentials"])

    def test_owner_mentions_inherit_tag_mode_accept_edits(self):
        # Upstream src/modes/tag/index.ts:159-214 grants workspace edits only
        # through --permission-mode acceptEdits; base-action parse-sdk-options.ts
        # keeps the last --permission-mode, so any workflow value replaces it.
        # Runs 40645284158 and 40645479186 were refused every Edit and Write.
        workflow = yaml.safe_load(MENTIONS.read_text())
        mention = workflow["jobs"]["claude"]
        invocation = next(
            step
            for step in mention["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        args = shlex.split(invocation["with"]["claude_args"])
        self.assertEqual(
            invocation["uses"],
            "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb",
        )
        self.assertEqual(
            set(invocation["with"]), {"claude_code_oauth_token", "claude_args"}
        )
        self.assertEqual(args, ["--strict-mcp-config", "--model", "claude-opus-5-5"])
        self.assertEqual(mention["permissions"]["contents"], "write")
        # Pin both branches and the outer sender gate, including their grouping.
        expected = (
            "github.event.sender.login == github.repository_owner "
            "&& ((github.event_name == 'issue_comment' "
            "&& contains(github.event.comment.body, '@claude') "
            "&& github.event.issue.user.login == github.repository_owner "
            "&& github.event.comment.user.login != 'claude[bot]' "
            "&& github.event.comment.user.type != 'Bot') "
            "|| (github.event_name == 'issues' "
            "&& github.event.issue.user.login == github.repository_owner "
            "&& (contains(github.event.issue.body, '@claude') "
            "|| contains(github.event.issue.title, '@claude'))))"
        )
        self.assertEqual(" ".join(mention["if"].split()), expected)

    def test_owner_mentions_serialize_branch_writes(self):
        workflow = yaml.safe_load(MENTIONS.read_text())
        mention = workflow["jobs"]["claude"]
        # source: GitHub Actions concurrency serializes owner requests per thread.
        self.assertEqual(
            mention["concurrency"],
            {
                "group": "claude-mentions-${{ github.event.issue.number }}",
                "cancel-in-progress": False,
            },
        )

    def test_automatic_review_pins_complete_invocation(self):
        # source: .github/workflows/claude-review.yml and upstream docs/solutions.md.
        workflow = yaml.safe_load(REVIEW.read_text())
        review = workflow["jobs"]["review"]
        invocation = next(
            step
            for step in review["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        self.assertEqual(
            set(invocation["with"]),
            {
                "claude_code_oauth_token",
                "track_progress",
                "allowed_bots",
                "prompt",
                "claude_args",
            },
        )
        args = shlex.split(invocation["with"]["claude_args"])
        self.assertEqual(
            args,
            [
                "--strict-mcp-config",
                "--permission-mode",
                "auto",
                "--allowedTools",
                "mcp__github_inline_comment__create_inline_comment,"
                "Bash(gh pr comment:*),Bash(gh pr diff:*),Bash(gh pr view:*)",
                "--model",
                "claude-opus-5-5",
            ],
        )

    def test_automatic_review_uses_upstream_app_supported_event(self):
        workflow = yaml.safe_load(REVIEW.read_text())
        events = workflow.get("on", workflow.get(True))
        self.assertIn("pull_request", events)
        self.assertNotIn("pull_request_target", events)
        self.assertIn("ready_for_review", events["pull_request"]["types"])

    def test_automatic_review_excludes_forks_and_drafts(self):
        workflow = yaml.safe_load(REVIEW.read_text())
        predicate = workflow["jobs"]["review"]["if"]
        self.assertIn("head.repo.full_name == github.repository", predicate)
        self.assertIn("!github.event.pull_request.draft", predicate)
        self.assertEqual(workflow["permissions"], {})

    def test_review_loads_trusted_configuration_before_receiving_authority(self):
        workflow = yaml.safe_load(REVIEW.read_text())
        steps = workflow["jobs"]["review"]["steps"]
        checkouts = [
            step
            for step in steps
            if step.get("uses", "").startswith("actions/checkout@")
        ]
        self.assertEqual(len(checkouts), 1)
        checkout = checkouts[0]
        self.assertEqual(checkout["with"].get("ref"), "main")
        self.assertFalse(checkout["with"].get("persist-credentials", True))
        invocation = next(
            step
            for step in steps
            if step.get("uses", "").startswith("anthropics/claude-code-action@")
        )
        self.assertLess(steps.index(checkout), steps.index(invocation))

    def test_native_progress_publication_uses_config_restoring_action(self):
        # Upstream run.ts restores sensitive config from base before starting CLI.
        # track_progress enables native progress and final-summary publication.
        workflow = yaml.safe_load(REVIEW.read_text())
        steps = workflow["jobs"]["review"]["steps"]
        invocation = next(
            step for step in steps if "claude-code-action@" in step.get("uses", "")
        )
        self.assertTrue(invocation["with"].get("track_progress"))
        self.assertEqual(
            invocation["uses"],
            "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb",
        )
        self.assertTrue(invocation["with"]["prompt"].startswith("/review-pr "))

    def test_existing_bot_actors_can_trigger_the_review(self):
        workflow = yaml.safe_load(REVIEW.read_text())
        steps = workflow["jobs"]["review"]["steps"]
        invocation = next(
            step for step in steps if "claude-code-action@" in step.get("uses", "")
        )
        allowed = invocation["with"].get("allowed_bots", "").split(",")
        self.assertEqual(
            set(allowed),
            {"claude[bot]", "chatgpt-codex-connector[bot]", "dependabot[bot]"},
        )


if __name__ == "__main__":
    unittest.main()
