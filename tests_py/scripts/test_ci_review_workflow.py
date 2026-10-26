"""Keep denied execution from satisfying the generated review job.

Source: Cortex PR796, run40200974594 attempt2, review job121876760991.
"""

from pathlib import Path
import re
import unittest


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/pipeline.yml"


class ReviewExecutionWiringTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_each_action_is_validated_before_another_can_overwrite_its_execution(self):
        for action, next_step in (("Review", "Fix"), ("Fix", "merge:")):
            with self.subTest(action=action):
                start = self.text.index(f"      - name: {action}\n")
                marker = "      - name: Fix\n" if next_step == "Fix" else "\n  merge:\n"
                end = self.text.index(marker, start + len(action) + 20)
                block = self.text[start:end]
                self.assertIn(f"id: {action.lower()}_action", block)
                self.assertIn(f"- name: Validate {action.lower()} execution", block)
                self.assertIn(
                    f"EXECUTION_FILE: ${{{{ steps.{action.lower()}_action"
                    ".outputs.execution_file }}",
                    block,
                )
                self.assertIn(
                    'python3 scripts/ci_review_execution.py "$EXECUTION_FILE"', block
                )
                self.assertNotIn("continue-on-error", block)

    def test_review_requires_agents_and_fix_does_not(self):
        commands = re.findall(
            r"run: (python3 scripts/ci_review_execution.py[^\n]+)", self.text
        )
        self.assertEqual(len(commands), 2)
        self.assertTrue(commands[0].endswith(" --require-agents"))
        self.assertNotIn("--require-agents", commands[1])

    def test_validation_runs_for_executed_actions_including_action_failure(self):
        for action in ("review", "fix"):
            with self.subTest(action=action):
                start = self.text.index(f"      - name: Validate {action} execution\n")
                block = self.text[start:].split("\n      - name:", 1)[0]
                self.assertIn("always() && !cancelled()", block)
                self.assertIn(f"steps.{action}_action.outcome != 'skipped'", block)


if __name__ == "__main__":
    unittest.main()
