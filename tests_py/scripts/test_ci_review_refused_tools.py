"""Behaviour of the "Refused tool calls" step of the review workflow (ADR-1138).

The step's script runs under bash with jq against fixture execution files: what
it prints is observed, not the text of the workflow.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tests_py.scripts._ci_native_claude_support import ACTION, find_step

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / ".github/workflows/claude-review.yml"
STEP = "Refused tool calls"
TOOLS_ON_PATH = bool(shutil.which("jq") and shutil.which("bash"))


def _review_job():
    return yaml.safe_load(REVIEW.read_text())["jobs"]["review"]


def _denial(name, **tool_input):
    return {"tool_name": name, "tool_use_id": "toolu_x", "tool_input": tool_input}


def _execution(*denials, with_result=True):
    messages = [{"type": "system", "subtype": "init"}, {"type": "assistant"}]
    if with_result:
        messages.append(
            {"type": "result", "subtype": "success", "permission_denials": [*denials]}
        )
    return json.dumps(messages)


def _run_step(content):
    """Run the step's script on an execution file holding `content`.

    Returns the completed process and what the step added to the summary."""
    script = find_step(_review_job(), name=STEP)["run"]
    with tempfile.TemporaryDirectory() as scratch:
        execution = Path(scratch) / "claude-execution-output.json"
        execution.write_text(content)
        summary = Path(scratch) / "summary.md"
        env = {
            "PATH": os.environ["PATH"],
            "EXECUTION_FILE": str(execution),
            "GITHUB_STEP_SUMMARY": str(summary),
        }
        # GitHub runs a `run:` block with `bash -e -o pipefail`.
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return result, summary.read_text() if summary.exists() else ""


class RefusedToolCallsStep(unittest.TestCase):
    def setUp(self):
        if not TOOLS_ON_PATH:
            if os.environ.get("CI"):
                self.fail("bash and jq must be on PATH in CI")
            self.skipTest("needs bash and jq")

    def test_names_and_counts_each_refused_tool(self):
        run, summary = _run_step(
            _execution(
                _denial("Bash", command="python3 -m pytest"),
                _denial("Skill", skill="review-pr"),
                _denial("Bash", command="git status"),
            )
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            run.stdout.splitlines(), ["refused: Bash x2", "refused: Skill x1"]
        )
        self.assertEqual(summary, run.stdout)

    def test_prints_no_tool_input(self):
        run, summary = _run_step(
            _execution(_denial("Bash", command="curl -H 'Authorization: s3cr3t'"))
        )
        self.assertEqual(run.stdout.splitlines(), ["refused: Bash x1"])
        self.assertNotIn("s3cr3t", run.stdout + run.stderr + summary)

    def test_says_none_when_nothing_was_refused(self):
        for content in (_execution(), _execution(with_result=False)):
            with self.subTest(content=content):
                run, _ = _run_step(content)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout.splitlines(), ["refused: none"])

    def test_a_name_cannot_form_a_workflow_command(self):
        run, _ = _run_step(
            _execution(
                _denial("::error::x\n::add-mask::y"), _denial(""), _denial("a b")
            )
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            run.stdout.splitlines(),
            ["refused: ab x1", "refused: errorxadd-masky x1", "refused: unnamed x1"],
        )
        self.assertNotIn("::", run.stdout)

    def test_an_unreadable_file_is_said_and_does_not_fail_the_job(self):
        for content in ("not json", json.dumps({"type": "result"})):
            with self.subTest(content=content):
                run, summary = _run_step(content)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(
                    run.stdout.splitlines(),
                    ["refused: the execution file could not be read"],
                )
                self.assertEqual(summary, run.stdout)


class RefusedToolCallsWiring(unittest.TestCase):
    def test_the_step_reads_the_file_of_the_review_step_and_always_runs(self):
        job = _review_job()
        review = find_step(job, uses=ACTION)
        self.assertEqual(review.get("id"), "review")
        step = find_step(job, name=STEP)
        self.assertGreater(job["steps"].index(step), job["steps"].index(review))
        self.assertEqual(
            step["if"],
            "${{ always() && steps.review.outputs.execution_file != '' }}",
        )
        self.assertEqual(
            step["env"],
            {"EXECUTION_FILE": "${{ steps.review.outputs.execution_file }}"},
        )
        self.assertNotIn("uses", step)

    def test_the_step_runs_nothing_from_the_checkout(self):
        script = find_step(_review_job(), name=STEP)["run"]
        for word in ("python", "scripts/", "./", "bash ", "source ", "eval"):
            self.assertNotIn(word, script)


if __name__ == "__main__":
    unittest.main()
