"""Each automatic Claude review in claude.yml must prove its own completed execution."""

from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
import unittest

from tests_py.scripts.test_ci_review_skills import execution

ROOT = Path(__file__).resolve().parents[2]
CLAUDE = (ROOT / ".github/workflows/claude.yml").read_text()
PIPELINE = (ROOT / ".github/workflows/pipeline.yml").read_text()
REVIEW_JOB = CLAUDE.split("\n  review:\n", 1)[1]


def step(text, name):
    return text.split(f"      - name: {name}\n", 1)[1].split("\n      - name:", 1)[0]


def command(block):
    return block.split("        run: ", 1)[1].strip()


class ReviewPhaseTests(unittest.TestCase):
    def test_each_phase_enforces_its_own_skill_and_agent_completion(self):
        # Source: official code-review steps 1-4 use seven agents; owner requires
        # independent completed security agent evidence for the security phase.
        for phase, skill, agents in (
            ("code review", "code-review:code-review", 7),
            ("security review", "security-review", 1),
        ):
            with self.subTest(phase=phase):
                self.assert_phase(phase, execution((skill,), agents), 0)
                self.assert_phase(phase, execution((), agents), 1)
                self.assert_phase(phase, execution((skill,), agents - 1), 1)

    def assert_phase(self, phase, messages, expected):
        run = command(step(REVIEW_JOB, f"Validate {phase} execution"))
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "execution.json"
            evidence.write_text(json.dumps(messages))
            done = subprocess.run(
                ["bash", "-eo", "pipefail", "-c", run],
                cwd=ROOT,
                env={**os.environ, "EXECUTION_FILE": str(evidence)},
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(done.returncode, expected, done.stderr)

    def test_validators_run_after_every_executed_action_without_skips(self):
        for phase, action in (
            ("code review", "code_review_action"),
            ("security review", "security_review_action"),
        ):
            with self.subTest(phase=phase):
                block = step(REVIEW_JOB, f"Validate {phase} execution")
                self.assertIn("always() && !cancelled()", block)
                self.assertIn(f"steps.{action}.outcome != 'skipped'", block)
                self.assertIn(f"steps.{action}.outputs.execution_file", block)
                self.assertNotIn("continue-on-error", block)

    def test_claude_checkouts_do_not_persist_the_workflow_token(self):
        review_job = PIPELINE.split("\n  review:\n", 1)[1].split("\n  merge:\n", 1)[0]
        for text in (review_job, CLAUDE):
            checkouts = re.findall(
                r"      - uses: actions/checkout@.*?(?=\n      -|\n\n|\Z)", text, re.S
            )
            self.assertTrue(checkouts)
        for checkout in re.findall(
            r"      - uses: actions/checkout@.*?(?=\n      -|\n\n|\Z)", REVIEW_JOB, re.S
        ):
            self.assertIn("persist-credentials: false", checkout)

    def test_reviews_publish_as_the_app_not_the_job_token(self):
        # gh prefers GH_TOKEN over the App token the action exports, and a
        # github_token input would replace the App identity: both are refused.
        self.assertNotIn("github_token", REVIEW_JOB)
        head = REVIEW_JOB.split("    steps:\n", 1)[0]
        self.assertNotIn("GH_TOKEN", head)
        for name in ("Code review", "Security review"):
            self.assertNotIn("GH_TOKEN", step(REVIEW_JOB, name))
        self.assertIn(
            "GH_TOKEN: ${{ github.token }}",
            step(REVIEW_JOB, "Read the PR head as data"),
        )

    def test_review_runs_trusted_main_and_reads_the_pr_as_data(self):
        self.assertIn(
            "workflow_run:\n    workflows: [Pipeline]\n    types: [requested]", CLAUDE
        )
        self.assertIn("ref: main", REVIEW_JOB)
        self.assertNotIn("pull_request.head.ref", REVIEW_JOB)
        read = step(REVIEW_JOB, "Read the PR head as data")
        self.assertIn("headRefOid", read)
        self.assertIn("gh pr diff", read)
        self.assertNotIn("git fetch", read)

    def test_mention_triggers_stay_alongside_the_automatic_review(self):
        for trigger in (
            "issue_comment:",
            "pull_request_review_comment:",
            "pull_request_review:",
            "issues:",
        ):
            self.assertIn(f"\n  {trigger}\n", CLAUDE)
        self.assertIn("contains(github.event.comment.body, '@claude')", CLAUDE)

    def test_each_review_is_native_and_security_runs_after_code_review_failure(self):
        for name, skill in (
            ("Code review", "code-review:code-review"),
            ("Security review", "security-review"),
        ):
            action = step(REVIEW_JOB, name)
            self.assertIn(f"skill {skill}", action)
            self.assertIn("env.HEAD_SHA", action)
            self.assertIn("dependabot[bot]", action)
        self.assertIn(
            "if: always() && !cancelled()", step(REVIEW_JOB, "Security review")
        )

    def test_pipeline_no_longer_hosts_a_claude_review(self):
        self.assertNotIn("native_review", PIPELINE)
        for name in ("Review", "Security review"):
            self.assertNotIn(f"      - name: {name}\n", PIPELINE)


if __name__ == "__main__":
    unittest.main()
