"""The embedded Pipeline gate and reader, executed with a fake gh (no network).

A PR cannot be blocked by a gate its own merge installs; once main requires
Claude, only run-bound claude[bot] reviews count, and a forged citation is an
answer (pending), never a red job.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests_py.scripts.test_ci_claude_wiring import CLAUDE_YML, SHA, command

LEGACY = "<!-- claude-review:v1 kind={} findings=0 -->"
FORGED = "<!-- claude-review:v2 kind={} findings=0 run=901-1 -->"


def encoded(text):
    content = base64.b64encode(text.encode()).decode()
    return {"type": "file", "encoding": "base64", "content": content}


def reviews(template):
    user = {"login": "claude[bot]", "type": "Bot"}
    rows = [
        {
            "id": i,
            "user": user,
            "commit_id": SHA,
            "state": "COMMENTED",
            "body": template.format(k),
        }
        for i, k in ((1, "code"), (2, "security"))
    ]
    return [rows]


class PipelineExecutionTests(unittest.TestCase):
    def fixture(self, root, listing, content, rows):
        repo = {"full_name": "cdeust/Cortex"}
        pull = {
            "state": "open",
            "draft": False,
            "head": {"sha": SHA, "repo": repo},
            "base": {"ref": "main", "repo": repo},
        }
        for name, value in (
            ("pull.json", pull),
            ("listing.json", listing),
            ("claude.json", content),
            ("reviews.json", rows),
        ):
            (root / name).write_text(json.dumps(value))
        (root / "calls").write_text("")
        gh = root / "gh"
        gh.write_text(
            '#!/bin/sh\necho "$*" >> "$FIXTURE/calls"\ncase "$*" in '
            '*workflows/claude.yml?ref=main*) cat "$FIXTURE/claude.json" ;; '
            '*workflows?ref=main*) cat "$FIXTURE/listing.json" ;; '
            '*/reviews*) cat "$FIXTURE/reviews.json" ;; '
            '*actions/runs/*) echo "$NOT_FOUND"; exit 1 ;; '
            '*) cat "$FIXTURE/pull.json" ;; esac\n'
        )
        gh.chmod(0o700)
        (root / "json.py").write_text("raise RuntimeError('candidate import')")

    def run_steps(self, root, completion_only):
        env = {
            **os.environ,
            "PATH": f"{root}:{os.environ['PATH']}",
            "FIXTURE": str(root),
            # gh api prints a 404 body on stdout and exits 1 (verified locally).
            "NOT_FOUND": '{"message":"Not Found","status":"404"}',
            "PYTHONPATH": str(root),
            "GH_REPO": "cdeust/Cortex",
            "PR": "804",
            "HEAD_SHA": SHA,
            "CLAUDE_COMPLETION_ONLY": str(completion_only).lower(),
        }
        gate_output = root / "gate"
        gate = subprocess.run(
            [
                "bash",
                "-eo",
                "pipefail",
                "-c",
                command("claude_gate_reader", "CLAUDE_GATE_PY"),
            ],
            cwd=root,
            env=dict(env, GITHUB_OUTPUT=str(gate_output)),
            capture_output=True,
            text=True,
        )
        self.assertEqual(gate.returncode, 0, gate.stderr)
        required = gate_output.read_text().strip().split("=", 1)[1]
        return subprocess.run(
            ["bash", "-eo", "pipefail", "-c", command()],
            cwd=root,
            env=dict(env, CLAUDE_REQUIRED=required, GITHUB_OUTPUT=str(root / "output")),
            capture_output=True,
            text=True,
        )

    def gate(self, listing, content, rows=None, completion_only=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.fixture(root, listing, content, rows if rows is not None else [[]])
        result = self.run_steps(root, completion_only)
        self.assertNotIn("candidate", result.stderr)
        return result, (root / "output").read_text(), (root / "calls").read_text()

    def required(self):
        text = CLAUDE_YML.read_text().replace(
            "  CLAUDE_REVIEW_GATE: observe", "  CLAUDE_REVIEW_GATE: required"
        )
        return [{"name": "claude.yml", "type": "file"}], encoded(text)

    def test_main_without_claude_workflow_is_codex_only(self):
        result, output, calls = self.gate(
            [{"name": "pipeline.yml", "type": "file"}], {}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "state=not_required\n")
        self.assertNotIn("/reviews", calls)

    def test_this_repository_claude_workflow_installs_in_observe_mode(self):
        text = CLAUDE_YML.read_text()
        self.assertEqual(text.count("\n  CLAUDE_REVIEW_GATE: "), 1)
        self.assertIn("\n  CLAUDE_REVIEW_GATE: observe\n", text)
        listing = [{"name": "claude.yml", "type": "file"}]
        result, output, calls = self.gate(listing, encoded(text))
        self.assertEqual((result.returncode, output), (0, "state=not_required\n"))
        self.assertNotIn("/reviews", calls)

    def test_required_gate_without_review_is_pending_never_failed(self):
        for completion_only, code in ((True, 0), (False, 2)):
            with self.subTest(completion_only=completion_only):
                result, output, _ = self.gate(*self.required(), None, completion_only)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn("state=pending", output)

    def test_marker_only_or_forged_citation_never_satisfies_required_gate(self):
        # Regression (coordinator msg_6cee25591704, Codex 4389070516): claude[bot]
        # markers without a validated producing run, and a citation of a run that
        # does not exist (gh exits 1 with a 404 body), stay pending, not green/red.
        for template in (LEGACY, FORGED):
            with self.subTest(template=template):
                rows = reviews(template)
                result, output, _ = self.gate(*self.required(), rows, False)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("state=pending", output)


if __name__ == "__main__":
    unittest.main()
