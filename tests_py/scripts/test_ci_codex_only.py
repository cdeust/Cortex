"""Owner decision: CI uses native Codex reviews without Claude actions."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CodexOnlyTests(unittest.TestCase):
    def test_no_workflow_runs_claude_actions_or_requires_claude_verdicts(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            with self.subTest(path=path.name):
                text = path.read_text()
                self.assertNotIn("anthropics/claude-code-action@", text)
                self.assertNotIn("Require complete Claude verdicts", text)

    def test_review_gate_needs_no_checkout_or_write_permission(self):
        text = (ROOT / ".github/workflows/pipeline.yml").read_text()
        review = text.split("\n  review:\n", 1)[1].split("\n  merge:\n", 1)[0]
        self.assertNotIn("actions/checkout@", review)
        self.assertNotIn(": write", review)
        self.assertIn("CODEX_COMPLETION_ONLY:", review)
        self.assertIn("Require completed Codex reviews", review)
