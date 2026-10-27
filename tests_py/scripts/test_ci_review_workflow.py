"""Keep denied execution from satisfying the generated review job.

Source: Cortex PR796, run40200974594 attempt2, review job121876760991.
"""

from pathlib import Path
import re
import json
import os
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/pipeline.yml"


class ReviewExecutionWiringTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_each_action_is_validated_before_another_can_overwrite_its_execution(self):
        for action, next_step in (("Fix", "merge:"),):
            with self.subTest(action=action):
                start = self.text.index(f"      - name: {action}\n")
                marker = (
                    f"      - name: {next_step}\n"
                    if next_step != "merge:"
                    else "\n  merge:\n"
                )
                end = self.text.index(marker, start + len(action) + 20)
                block = self.text[start:end]
                identifier = action.lower().replace(" ", "_")
                self.assertIn(f"id: {identifier}_action", block)
                self.assertIn(f"- name: Validate {action.lower()} execution", block)
                self.assertIn(
                    f"EXECUTION_FILE: ${{{{ steps.{identifier}_action"
                    ".outputs.execution_file }}",
                    block,
                )
                self.assertIn('python3 -I - "$EXECUTION_FILE"', block)
                if action == "Fix":
                    self.assertIn('git show "$VALIDATOR_REVISION:scripts/', block)
                    self.assertIn(
                        "VALIDATOR_REVISION: ${{ github.event.pull_request.base.sha }}",
                        block,
                    )
                self.assertNotIn("continue-on-error", block)

    def test_fix_does_not_require_agents(self):
        # The two reviews and their agent counts are validated in claude.yml.
        commands = re.findall(r'python3 -I - "\$EXECUTION_FILE"[^\n]*', self.text)
        self.assertEqual(len(commands), 1)
        self.assertNotIn("--require-agents", commands[0])

    def test_validation_runs_for_executed_actions_including_action_failure(self):
        for action in ("fix",):
            with self.subTest(action=action):
                start = self.text.index(f"      - name: Validate {action} execution\n")
                block = self.text[start:].split("\n      - name:", 1)[0]
                self.assertIn("always() && !cancelled()", block)
                self.assertIn(
                    f"steps.{action.replace(' ', '_')}_action.outcome != 'skipped'",
                    block,
                )

    def validation_command(self):
        start = self.text.index("      - name: Validate fix execution\n")
        block = self.text[start:].split("\n  # Decision 4", 1)[0]
        command = block.split("        run: ", 1)[1]
        return textwrap.dedent(command[2:]) if command.startswith("|\n") else command

    def test_validator_and_python_imports_come_from_trusted_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_trusted_execution(Path(directory))

    def assert_trusted_execution(self, root):
        revision, execution = self.malicious_checkout(root)
        result = subprocess.run(
            ["bash", "-eo", "pipefail", "-c", self.validation_command()],
            cwd=root,
            env={
                **os.environ,
                "EXECUTION_FILE": str(execution),
                "VALIDATOR_REVISION": revision,
                "PYTHONPATH": str(root),
            },
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((root / "candidate-executed").exists())
        self.assertIn("execution verified", result.stdout)

    def malicious_checkout(self, root):
        scripts = root / "scripts"
        scripts.mkdir()
        helper = scripts / "ci_review_execution.py"
        helper.write_bytes(
            (WORKFLOW.parents[2] / helper.relative_to(root)).read_bytes()
        )
        self.git(root, "init", "-q")
        self.git(root, "add", "scripts/ci_review_execution.py")
        self.git(root, "commit", "-qm", "trusted validator")
        revision = self.git(root, "rev-parse", "HEAD").stdout.strip()
        payload = "from pathlib import Path; Path('candidate-executed').touch()\n"
        helper.write_text(payload)
        (root / "json.py").write_text(payload)
        execution = root / "execution.json"
        execution.write_text(
            json.dumps(
                [
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "permission_denials": [],
                    }
                ]
            )
        )
        return revision, execution

    def git(self, root, *args):
        return subprocess.run(
            [
                "git",
                "-c",
                "user.name=CI fixture",
                "-c",
                "user.email=ci@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(root),
                *args,
            ],
            text=True,
            capture_output=True,
            check=True,
        )

    def test_non_main_base_is_rejected_before_git_and_without_action_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_review_guard(root, {"BASE_REF": "untrusted-base"})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse((root / "git-calls").exists())
            self.assertFalse((root / "outputs").exists())

    def test_main_base_retains_normal_and_bootstrap_action_decisions(self):
        for changed, expected in (
            ("docs/a.md", "true"),
            (".github/workflows/pipeline.yml", "false"),
            (".github/workflows/claude.yml", "false"),
        ):
            with (
                self.subTest(changed=changed),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                result = self.run_review_guard(root, {"CHANGED": changed})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    (root / "outputs").read_text(),
                    f"review=true\nfix={expected}\n",
                )

    def run_review_guard(self, root, overrides):
        fake_git = root / "git"
        fake_git.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$GIT_CALLS"\n'
            'case "$1" in\n'
            'rev-parse) printf "%s\\n" "$HEAD_SHA" ;;\n'
            'diff) printf "%s\\n" "$CHANGED" ;;\n'
            "symbolic-ref) exit 0 ;;\n"
            'log) printf "ci@example.invalid\\n" ;;\n'
            "*) exit 2 ;;\nesac\n"
        )
        fake_git.chmod(0o700)
        start = self.text.index("      - name: Review guard\n")
        block = self.text[start:].split("\n      - name:", 1)[0]
        command = textwrap.dedent(block.split("        run: |\n", 1)[1])
        # Source: pipeline.yml Review guard environment; synthetic full SHA-1.
        env = {
            **os.environ,
            "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
            "BASE_REF": "main",
            "HEAD_SHA": "a" * 40,
            "CHANGED": "docs/a.md",
            "TEST_RESULTS": "{}",
            "GIT_CALLS": str(root / "git-calls"),
            "GITHUB_OUTPUT": str(root / "outputs"),
            "GITHUB_STEP_SUMMARY": str(root / "summary"),
            **overrides,
        }
        return subprocess.run(
            ["bash", "-eo", "pipefail", "-c", command],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
