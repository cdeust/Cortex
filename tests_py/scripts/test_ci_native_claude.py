"""Regression for native Codex finding4392874807: PR-controlled reviewer config."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class NativeClaudeTrustTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
