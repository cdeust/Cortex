"""The privileged gate uses workflow code, never candidate Python imports."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".github/workflows/pipeline.yml"
READER = ROOT / "scripts/ci_codex_reviews.py"
SHA = "a" * 40  # GitHub SHA-1 field, synthetic fixture.


def command():
    text = PIPELINE.read_text()
    block = text.split("        run: &codex_review_reader |\n", 1)[1]
    return (
        textwrap.dedent(block.split("\n          CODEX_REVIEW_PY", 1)[0])
        + "\nCODEX_REVIEW_PY\n"
    )


class CodexWiringTests(unittest.TestCase):
    def test_workflow_embeds_exact_reader_and_reuses_it_for_merge(self):
        run = command()
        source = run.split("<<'CODEX_REVIEW_PY'\n", 1)[1].split("\nCODEX_REVIEW_PY", 1)[
            0
        ]
        self.assertEqual(source + "\n", READER.read_text())
        text = PIPELINE.read_text()
        self.assertEqual(text.count("run: *codex_review_reader"), 1)
        self.assertIn('python3 -I - "${args[@]}"', run)
        self.assertNotIn("git show", run)

    def test_pre_fix_requires_completion_and_merge_requires_cleanliness(self):
        text = PIPELINE.read_text()
        readiness = text.index(
            "      - name: Require completed Codex reviews for repair\n"
        )
        self.assertLess(readiness, text.index("      - name: Fix\n"))
        block = text[readiness:].split("\n      - name:", 1)[0]
        self.assertIn("steps.guard.outputs.fix == 'true'", block)
        self.assertIn("CODEX_COMPLETION_ONLY: 'true'", block)
        merge = text.split("\n  merge:\n", 1)[1]
        self.assertIn("      - name: Require complete Codex reviews\n", merge)
        self.assertIn("CODEX_COMPLETION_ONLY: 'false'", merge)

    def test_current_clean_and_pending_evidence_with_poisoned_checkout(self):
        for completed in (True, False):
            with (
                self.subTest(completed=completed),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                (root / "json.py").write_text("raise RuntimeError('candidate import')")
                (root / "scripts").mkdir()
                (root / "scripts/ci_codex_reviews.py").write_text(
                    "raise RuntimeError('candidate code')"
                )
                self.seed_comments(root, completed)
                result = self.run_gate(root, completed)
                self.assertEqual(
                    result.returncode, 0 if completed else 2, result.stderr
                )
                self.assertNotIn("candidate", result.stderr)

    def run_gate(self, root, completed):
        repo = {"full_name": "cdeust/Cortex"}
        pull = {
            "state": "open",
            "draft": False,
            "head": {"sha": SHA, "repo": repo},
            "base": {"ref": "main", "repo": repo},
        }
        (root / "pull.json").write_text(json.dumps(pull))
        gh = root / "gh"
        gh.write_text(
            '#!/bin/sh\ncase "$*" in '
            '*comments*) cat "$FIXTURE/comments.json" ;; '
            '*) cat "$FIXTURE/pull.json" ;; esac\n'
        )
        gh.chmod(0o700)
        return subprocess.run(
            ["bash", "-eo", "pipefail", "-c", command()],
            cwd=root,
            env={
                **os.environ,
                "PATH": f"{root}:{os.environ['PATH']}",
                "FIXTURE": str(root),
                "PYTHONPATH": str(root),
                "GH_REPO": "cdeust/Cortex",
                "PR": "797",
                "HEAD_SHA": SHA,
                "CODEX_COMPLETION_ONLY": "false",
            },
            capture_output=True,
            text=True,
        )

    def seed_comments(self, root, completed):
        user = {"login": "chatgpt-codex-connector[bot]", "type": "Bot"}
        review = {
            "status": "completed" if completed else "running",
            "commit_sha": SHA,
            "has_any_findings": False,
            "has_unresolved_findings": False,
        }
        summary = {"code_review": review, "security_review": review}
        body = "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "
        body += json.dumps(summary) + " -->"
        comments = [
            [
                {
                    "id": 1,
                    "updated_at": "2026-10-27T00:00:00Z",
                    "user": user,
                    "body": body,
                }
            ]
        ]
        (root / "comments.json").write_text(json.dumps(comments))

    def test_completion_workflow_never_checks_out_candidate_or_uses_oauth(self):
        text = (ROOT / ".github/workflows/Codex.yml").read_text()
        self.assertIn("types: [created, edited]", text)
        self.assertIn("workflows: [Pipeline]", text)
        self.assertIn("ref: main", text)
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("head.ref", text)
        # Source: GitHub events reference: this event uses the PR merge branch,
        # so even checkout main cannot protect its Actions-write job definition.
        self.assertNotIn("pull_request_review:", text)
        self.assertIn("actions: write", text)
        self.assertIn("cancel-in-progress: false", text)


if __name__ == "__main__":
    unittest.main()
