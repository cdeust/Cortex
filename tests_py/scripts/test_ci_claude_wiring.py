"""Workflow contracts of the claude[bot] review path and its Pipeline gate.

Sources: GitHub events reference (workflow_run runs the default-branch file;
pull_request_review runs refs/pull/N/merge), anthropics/claude-code-action
v1.0.263 src/github/token.ts (OIDC exchange refuses a workflow that differs
from the default branch) and action.yml (App token revoked after the step).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".github/workflows/pipeline.yml"
CLAUDE_YML = ROOT / ".github/workflows/claude.yml"
CODEX_YML = ROOT / ".github/workflows/Codex.yml"
READER = ROOT / "scripts/ci_claude_reviews.py"
GATE = ROOT / "scripts/ci_claude_review_gate.py"
SHA = "a" * 40  # GitHub SHA-1 field, synthetic fixture.
# source: upstream tag v1.0.263, docs/verification/claude-bot-ci-20261027.md
PIN = (
    "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb # v1.0.263"
)


def job(text, name):
    body = text.split(f"\n  {name}:\n", 1)[1]
    return re.split(r"\n  [a-z][a-z_-]*:\n", body, maxsplit=1)[0]


def command(anchor="claude_review_reader", heredoc="CLAUDE_REVIEW_PY"):
    """The embedded step script of a pipeline.yml run anchor, dedented."""
    block = PIPELINE.read_text().split(f"        run: &{anchor} |\n", 1)[1]
    return (
        textwrap.dedent(block.split(f"\n          {heredoc}", 1)[0]) + f"\n{heredoc}\n"
    )


class PipelineGateTests(unittest.TestCase):
    def test_pipeline_embeds_exact_gate_and_reader_once_each(self):
        text = PIPELINE.read_text()
        for anchor, heredoc, script in (
            ("claude_review_reader", "CLAUDE_REVIEW_PY", READER),
            ("claude_gate_reader", "CLAUDE_GATE_PY", GATE),
        ):
            with self.subTest(anchor=anchor):
                run = command(anchor, heredoc)
                source = run.split(f"<<'{heredoc}'\n", 1)[1]
                source = source.split(f"\n{heredoc}", 1)[0]
                self.assertEqual(source + "\n", script.read_text())
                self.assertEqual(text.count(f"run: *{anchor}"), 1)
                self.assertIn("python3 -I - ", run)
        # Only the gate read from main decides that Claude is required.
        shell = command().split("<<'CLAUDE_REVIEW_PY'\n", 1)[0]
        self.assertIn('if [ "$CLAUDE_REQUIRED" != true ]', shell)
        self.assertIn("steps.claude_gate.outputs.required", text)

    def test_soft_skipped_action_fails_execution_validation(self):
        # An action that soft-skips on workflow validation leaves no execution file.
        done = subprocess.run(
            [
                "python3",
                "-I",
                str(ROOT / "scripts/ci_review_execution.py"),
                "",
                "--require-skill",
                "security-review",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 1)
        review = job(CLAUDE_YML.read_text(), "review")
        for step in (
            "Validate code review execution",
            "Validate security review execution",
        ):
            block = review.split(f"      - name: {step}\n", 1)[1].split(
                "\n      - ", 1
            )[0]
            self.assertIn("!cancelled()", block)
            self.assertNotIn("outcome", block)

    def test_review_combines_states_and_merge_requires_clean_claude(self):
        text = PIPELINE.read_text()
        review = job(text, "review")
        step = review.split("      - name: Require completed Claude reviews\n", 1)[1]
        step = step.split("\n      - name:", 1)[0]
        self.assertNotIn("        if:", step)
        self.assertIn("CLAUDE_COMPLETION_ONLY: 'true'", step)
        self.assertIn("state: ${{ steps.state.outputs.state }}", review)
        merge = text.split("\n  merge:\n", 1)[1].split("\n  tag:\n", 1)[0]
        claude = merge.split("      - name: Require complete Claude reviews\n", 1)[1]
        claude = claude.split("\n      - name:", 1)[0]
        self.assertIn("if: needs.review.outputs.state != 'pending'", claude)
        self.assertIn("CLAUDE_COMPLETION_ONLY: 'false'", claude)

    def test_combined_state_is_pending_when_either_source_is_pending(self):
        review = job(PIPELINE.read_text(), "review")
        script = review.split("      - name: Combine review states\n", 1)[1]
        script = textwrap.dedent(script.split("        run: |\n", 1)[1])
        for codex, claude, expected in (
            ("success", "pending", "pending"),
            ("pending", "not_required", "pending"),
            ("success", "not_required", "success"),
            ("success", "success", "success"),
            ("blocked", "success", "blocked"),
            ("success", "blocked", "blocked"),
            ("", "", "blocked"),
        ):
            with (
                self.subTest(codex=codex, claude=claude),
                tempfile.TemporaryDirectory() as d,
            ):
                output = Path(d) / "out"
                env = dict(
                    os.environ, CODEX=codex, CLAUDE=claude, GITHUB_OUTPUT=str(output)
                )
                done = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", script], env=env
                )
                self.assertEqual(done.returncode, 0)
                self.assertEqual(output.read_text(), f"state={expected}\n")


if __name__ == "__main__":
    unittest.main()
