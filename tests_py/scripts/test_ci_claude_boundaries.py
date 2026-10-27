"""Review boundaries: native Codex reviews plus claude[bot] reviews (2026-10-27).

Owner decision 2026-10-27 (docs/verification/claude-bot-ci-20261027.md):
restore genuine claude[bot] code and security reviews alongside Codex. The
Claude action runs only in claude.yml, from main, never inside the Pipeline.
"""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReviewBoundaryTests(unittest.TestCase):
    def test_claude_action_runs_only_in_the_claude_workflow(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            with self.subTest(path=path.name):
                text = path.read_text()
                if path.name != "claude.yml":
                    self.assertNotIn("anthropics/claude-code-action@", text)
                self.assertNotIn("Require complete Claude verdicts", text)
        self.assertIn(
            "anthropics/claude-code-action@",
            (ROOT / ".github/workflows/claude.yml").read_text(),
        )

    def test_review_gate_needs_no_checkout_or_write_permission(self):
        text = (ROOT / ".github/workflows/pipeline.yml").read_text()
        review = text.split("\n  review:\n", 1)[1].split("\n  merge:\n", 1)[0]
        self.assertNotIn("actions/checkout@", review)
        self.assertNotIn(": write", review)
        self.assertNotIn("secrets.", review)
        self.assertIn("CODEX_COMPLETION_ONLY:", review)
        self.assertIn("Require completed Codex reviews", review)
        self.assertIn("CLAUDE_COMPLETION_ONLY:", review)
        self.assertIn("Require completed Claude reviews", review)

    def test_control_plane_brief_forbids_candidate_execution_and_hooks(self):
        brief = (ROOT / "docs/automation/codex-worker.md").read_text()
        for boundary in (
            "NEVER CHECK OUT, DOWNLOAD TO LOCAL FILES, IMPORT OR EXECUTE PR CODE.",
            "All executable verification runs on GitHub-hosted CI runners",
            "Do not invoke git commit or any candidate hook",
            "force=false",
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, brief)
