"""Each automatic native review must prove its own completed execution."""

from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
import unittest

from tests_py.scripts.test_ci_review_skills import execution

ROOT = Path(__file__).resolve().parents[2]


def step(text, name):
    return text.split(f"      - name: {name}\n", 1)[1].split("\n      - name:", 1)[0]


def run_script(block):
    lines = []
    for line in block.split("        run: |\n", 1)[1].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line[10:])
    return "\n".join(lines)


class ReviewPhaseTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/pipeline.yml").read_text()

    def test_both_inline_validators_match_the_reviewed_helper_exactly(self):
        expected = (ROOT / "scripts/ci_review_execution.py").read_text()
        for phase in ("review", "security review"):
            with self.subTest(phase=phase):
                block = step(self.workflow, f"Validate {phase} execution")
                run = run_script(block)
                embedded = run.split("<<'PY_REVIEW'\n", 1)[1].rsplit("\nPY_REVIEW", 1)[
                    0
                ]
                self.assertEqual(embedded + "\n", expected)

    def test_each_phase_enforces_its_own_skill_and_agent_completion(self):
        # Source: official code-review steps 1-4 use seven agents; owner requires
        # independent completed security agent evidence for the security phase.
        for phase, skill, agents in (
            ("review", "code-review:code-review", 7),
            ("security review", "security-review", 1),
        ):
            with self.subTest(phase=phase):
                self.assert_phase(phase, execution((skill,), agents), 0)
                self.assert_phase(phase, execution((), agents), 1)
                self.assert_phase(phase, execution((skill,), agents - 1), 1)

    def assert_phase(self, phase, messages, expected):
        run = run_script(step(self.workflow, f"Validate {phase} execution"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "execution.json"
            evidence.write_text(json.dumps(messages))
            (root / "json.py").write_text("raise AssertionError('candidate executed')")
            done = subprocess.run(
                ["bash", "-eo", "pipefail", "-c", run],
                cwd=root,
                env={
                    **os.environ,
                    "EXECUTION_FILE": str(evidence),
                    "PYTHONPATH": directory,
                },
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(done.returncode, expected, done.stderr)
        self.assertNotIn("candidate executed", done.stderr)

    def test_claude_checkouts_do_not_persist_the_workflow_token(self):
        review_job = self.workflow.split("\n  review:\n", 1)[1].split(
            "\n  merge:\n", 1
        )[0]
        for text in (review_job, (ROOT / ".github/workflows/claude.yml").read_text()):
            checkouts = re.findall(
                r"      - uses: actions/checkout@.*?(?=\n      -|\Z)", text, re.S
            )
            self.assertTrue(checkouts)
            for checkout in checkouts:
                self.assertIn("persist-credentials: false", checkout)

    def test_readonly_review_has_no_actor_or_workflow_exemption(self):
        job = self.workflow.split("\n  review:\n", 1)[1].split("    steps:\n", 1)[0]
        self.assertNotIn("dependabot", job)
        guard = step(self.workflow, "Review guard")
        self.assertNotIn("review=false", guard)
        self.assertNotIn("claude[bot]", guard)
        for name, skill in (
            ("Review", "code-review:code-review"),
            ("Security review", "security-review"),
        ):
            action = step(self.workflow, name)
            self.assertIn(f"skill {skill}", action)
            self.assertIn("github.event.pull_request.head.sha", action)
            self.assertIn("dependabot[bot]", action)

    def test_security_is_attempted_even_when_code_review_failed(self):
        action = step(self.workflow, "Security review")
        self.assertIn(
            "if: always() && !cancelled() && steps.guard.outputs.review == 'true'",
            action,
        )


if __name__ == "__main__":
    unittest.main()
