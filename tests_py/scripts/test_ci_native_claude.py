"""Regression for native Codex finding4392874807: PR-controlled reviewer config."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class NativeClaudeTrustTests(unittest.TestCase):
    def test_target_review_uses_supported_explicit_github_authentication(self):
        # Upstream issue713: target-event OIDC exchange returns401.
        workflow = yaml.safe_load((ROOT / ".github/workflows/claude.yml").read_text())
        review = workflow["jobs"]["review"]
        invocation = next(
            step
            for step in review["steps"]
            if "claude-code-action@" in step.get("uses", "")
        )
        self.assertEqual(
            invocation["with"].get("github_token"), "${{ secrets.GITHUB_TOKEN }}"
        )
        self.assertEqual(
            review["permissions"], {"contents": "read", "pull-requests": "write"}
        )

    def test_owner_mentions_keep_app_authentication(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/claude.yml").read_text())
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

    def test_privileged_review_uses_base_workflow(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/claude.yml").read_text())
        events = workflow.get("on", workflow.get(True))
        self.assertIn("pull_request_target", events)
        self.assertNotIn("pull_request", events)
        self.assertIn("'pull_request_target'", workflow["jobs"]["review"]["if"])

    def test_review_loads_trusted_configuration_before_receiving_authority(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/claude.yml").read_text())
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

    def test_action_preparation_preserves_trusted_checkout(self):
        # Upstream detector.ts forces tag mode and PR checkout for track_progress.
        workflow = yaml.safe_load((ROOT / ".github/workflows/claude.yml").read_text())
        steps = workflow["jobs"]["review"]["steps"]
        invocation = next(
            step for step in steps if "claude-code-action@" in step.get("uses", "")
        )
        self.assertNotIn("track_progress", invocation["with"])
        self.assertTrue(invocation["with"]["prompt"].startswith("/review-pr "))

    def test_existing_bot_actors_can_trigger_the_review(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/claude.yml").read_text())
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
