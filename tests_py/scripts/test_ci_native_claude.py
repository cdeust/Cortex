"""Regression guards for native Claude configuration, authority and edit mode."""

import shlex
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / ".github/workflows/claude-review.yml"
MENTIONS = ROOT / ".github/workflows/claude.yml"


class NativeClaudeTrustTests(unittest.TestCase):
    def test_automatic_review_prompt_requires_github_comments(self):
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
        self.assertEqual(
            invocation["uses"],
            "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb",
        )
        self.assertEqual(
            set(invocation["with"]),
            {"claude_code_oauth_token", "include_comments_by_actor", "claude_args"},
        )
        self.assertEqual(
            invocation["with"]["include_comments_by_actor"],
            "${{ github.repository_owner }}",
        )
        self.assertNotIn("--permission-mode", invocation["with"]["claude_args"])
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

    def test_owner_mentions_allow_the_validation_commands_only(self):
        # Tag mode supplies no shell allowlist beyond scoped git; headless, an
        # unlisted command is denied (src/modes/tag/index.ts#L148-L201 at the
        # pinned SHA). The list is CLAUDE.md's validation set; never Bash(bash:*).
        workflow = yaml.safe_load(MENTIONS.read_text())
        invocation = next(
            step
            for step in workflow["jobs"]["claude"]["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        args = shlex.split(invocation["with"]["claude_args"])
        self.assertEqual(
            args,
            [
                "--strict-mcp-config",
                "--allowedTools",
                "Bash(git:*),Bash(gh:*),Bash(uv:*),Bash(pytest:*),"
                "Bash(python:*),Bash(python3:*),Bash(ruff:*)",
                "--model",
                "claude-opus-5-5",
            ],
        )
        self.assertNotIn("Bash(bash:*)", invocation["with"]["claude_args"])

    def test_owner_mentions_authorize_the_fix_target_before_checkout(self):
        # The sender gate checks who asked, not which head the pinned action
        # checks out and pushes to (src/modes/tag/index.ts). A fork head or main
        # itself is refused before any checkout.
        workflow = yaml.safe_load(MENTIONS.read_text())
        steps = workflow["jobs"]["claude"]["steps"]
        guard = next(s for s in steps if s.get("name") == "Authorize owner fix target")
        checkout = next(
            s for s in steps if s.get("uses", "").startswith("actions/checkout@")
        )
        self.assertLess(steps.index(guard), steps.index(checkout))
        self.assertIn(".head.repo.full_name == $repo", guard["run"])
        self.assertIn(".head.ref != .base.repo.default_branch", guard["run"])
        self.assertIn("set -euo pipefail", guard["run"])
        self.assertEqual(guard["env"]["GH_TOKEN"], "${{ github.token }}")

    def test_owner_mentions_bound_the_run(self):
        # source: docs.github.com workflow-syntax#jobsjob_idtimeout-minutes;
        # the default is 360 minutes and the queue serializes per thread.
        workflow = yaml.safe_load(MENTIONS.read_text())
        self.assertEqual(workflow["jobs"]["claude"]["timeout-minutes"], 60)

    def test_owner_mentions_serialize_branch_writes(self):
        workflow = yaml.safe_load(MENTIONS.read_text())
        mention = workflow["jobs"]["claude"]
        # source: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
        self.assertEqual(
            mention["concurrency"],
            {
                "group": "claude-mentions-${{ github.event.issue.number }}",
                "cancel-in-progress": False,
                "queue": "max",
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
        # Dependabot events carry Dependabot secrets only; the OAuth token is
        # empty there and the action aborts (run 41180098727).
        self.assertIn("github.actor != 'dependabot[bot]'", predicate)
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
