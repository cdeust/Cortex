"""Workflow contracts of the claude[bot] review path and its Pipeline gate.

Sources: GitHub events reference (workflow_run runs the default-branch file;
pull_request_review runs refs/pull/N/merge), anthropics/claude-code-action
v1.0.263 src/github/token.ts (OIDC exchange refuses a workflow that differs
from the default branch) and action.yml (App token revoked after the step).
"""

from __future__ import annotations

import base64
import json
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
SHA = "a" * 40  # GitHub SHA-1 field, synthetic fixture.
# source: upstream tag v1.0.263, docs/verification/claude-bot-ci-20261027.md
PIN = (
    "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb # v1.0.263"
)


def job(text, name):
    body = text.split(f"\n  {name}:\n", 1)[1]
    return re.split(r"\n  [a-z][a-z_-]*:\n", body, maxsplit=1)[0]


def command():
    block = PIPELINE.read_text().split("        run: &claude_review_reader |\n", 1)[1]
    return (
        textwrap.dedent(block.split("\n          CLAUDE_REVIEW_PY", 1)[0])
        + "\nCLAUDE_REVIEW_PY\n"
    )


class PipelineGateTests(unittest.TestCase):
    def test_pipeline_embeds_exact_reader_once_and_reuses_it_for_merge(self):
        run = command()
        source = run.split("<<'CLAUDE_REVIEW_PY'\n", 1)[1].split(
            "\nCLAUDE_REVIEW_PY", 1
        )[0]
        self.assertEqual(source + "\n", READER.read_text())
        text = PIPELINE.read_text()
        self.assertEqual(text.count("run: *claude_review_reader"), 1)
        self.assertIn('python3 -I - "${args[@]}"', run)
        # The gate never bypasses main's activation line; only verify does.
        shell = run.split("<<'CLAUDE_REVIEW_PY'\n", 1)[0]
        self.assertNotIn("--assume-required", shell)

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


class BootstrapTests(unittest.TestCase):
    """A PR cannot be blocked by a gate its own merge installs."""

    def run_gate(self, root, listing, content, completion_only=True):
        repo = {"full_name": "cdeust/Cortex"}
        pull = {
            "state": "open",
            "draft": False,
            "head": {"sha": SHA, "repo": repo},
            "base": {"ref": "main", "repo": repo},
        }
        (root / "pull.json").write_text(json.dumps(pull))
        (root / "listing.json").write_text(json.dumps(listing))
        (root / "claude.json").write_text(json.dumps(content))
        (root / "reviews.json").write_text("[[]]")
        (root / "calls").write_text("")
        gh = root / "gh"
        gh.write_text(
            '#!/bin/sh\necho "$*" >> "$FIXTURE/calls"\ncase "$*" in '
            '*workflows/claude.yml?ref=main*) cat "$FIXTURE/claude.json" ;; '
            '*workflows?ref=main*) cat "$FIXTURE/listing.json" ;; '
            '*/reviews*) cat "$FIXTURE/reviews.json" ;; '
            '*) cat "$FIXTURE/pull.json" ;; esac\n'
        )
        gh.chmod(0o700)
        (root / "json.py").write_text("raise RuntimeError('candidate import')")
        return subprocess.run(
            ["bash", "-eo", "pipefail", "-c", command()],
            cwd=root,
            env={
                **os.environ,
                "PATH": f"{root}:{os.environ['PATH']}",
                "FIXTURE": str(root),
                "PYTHONPATH": str(root),
                "GH_REPO": "cdeust/Cortex",
                "PR": "804",
                "HEAD_SHA": SHA,
                "CLAUDE_COMPLETION_ONLY": str(completion_only).lower(),
                "GITHUB_OUTPUT": str(root / "output"),
            },
            capture_output=True,
            text=True,
        )

    def encoded(self, text):
        return {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(text.encode()).decode(),
        }

    def test_main_without_claude_workflow_is_codex_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_gate(
                root, [{"name": "pipeline.yml", "type": "file"}], {}, False
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("state=not_required", (root / "output").read_text())
            self.assertNotIn("/reviews", (root / "calls").read_text())

    def test_this_repository_claude_workflow_installs_in_observe_mode(self):
        text = CLAUDE_YML.read_text()
        self.assertEqual(text.count("\n  CLAUDE_REVIEW_GATE: "), 1)
        self.assertIn("\n  CLAUDE_REVIEW_GATE: observe\n", text)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            listing = [{"name": "claude.yml", "type": "file"}]
            result = self.run_gate(root, listing, self.encoded(text), False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("state=not_required", (root / "output").read_text())

    def test_required_gate_without_review_is_pending_never_failed(self):
        text = CLAUDE_YML.read_text().replace(
            "  CLAUDE_REVIEW_GATE: observe", "  CLAUDE_REVIEW_GATE: required"
        )
        listing = [{"name": "claude.yml", "type": "file"}]
        for completion_only, code in ((True, 0), (False, 2)):
            with (
                self.subTest(completion_only=completion_only),
                tempfile.TemporaryDirectory() as d,
            ):
                root = Path(d)
                result = self.run_gate(
                    root, listing, self.encoded(text), completion_only
                )
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn("state=pending", (root / "output").read_text())
                self.assertNotIn("candidate", result.stderr)


if __name__ == "__main__":
    unittest.main()
