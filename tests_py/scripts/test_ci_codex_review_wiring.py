"""The privileged gate uses workflow code, never candidate Python imports."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import textwrap
import unittest

from tests_py.scripts.test_ci_codex_reviews import BOT_NODE_ID, summary_pages

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".github/workflows/pipeline.yml"
READER = ROOT / "scripts/ci_codex_reviews.py"
RUNTIME = ROOT / "scripts/ci_codex_review_runtime.py"
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
        for name, path in (("RUNTIME_SOURCE", RUNTIME), ("READER_SOURCE", READER)):
            source = run.split(name + " = r" + chr(39) * 3 + "\n", 1)[1]
            source = source.split("\n" + chr(39) * 3, 1)[0]
            self.assertEqual(source + "\n", path.read_text())
        text = PIPELINE.read_text()
        self.assertEqual(text.count("run: *codex_review_reader"), 1)
        self.assertIn('python3 -I - "${args[@]}"', run)
        self.assertNotIn("git show", run)

    def test_review_requires_completion_and_merge_requires_cleanliness(self):
        text = PIPELINE.read_text()
        readiness = text.index("      - name: Require completed Codex reviews\n")
        block = text[readiness:].split("\n      - name:", 1)[0]
        self.assertNotIn("        if:", block)
        self.assertIn("CODEX_COMPLETION_ONLY: 'true'", block)
        merge = text.split("\n  merge:\n", 1)[1]
        self.assertIn("      - name: Require complete Codex reviews\n", merge)
        self.assertIn("CODEX_COMPLETION_ONLY: 'false'", merge)
        self.assertIn("if: needs.review.outputs.state != 'pending'", merge)
        self.assertIn("needs.review.outputs.state == 'pending'", merge)
        self.assertIn("'merge pending review' || 'merge'", merge)

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
                (root / "ci_codex_review_runtime.py").write_text(
                    "raise RuntimeError('candidate runtime')"
                )
                self.seed_comments(root, completed)
                result = self.run_gate(root, completed)
                self.assertEqual(
                    result.returncode, 0 if completed else 2, result.stderr
                )
                self.assertNotIn("candidate", result.stderr)

    def test_pending_observation_is_green_but_does_not_authorize_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.seed_comments(root, False)
            result = self.run_gate(root, False, completion_only=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("state=pending", (root / "output").read_text())
            self.assertIn("ready=false", (root / "output").read_text())

    def test_isolated_gate_uses_authenticated_thread_resolution(self):
        from tests_py.scripts.test_ci_codex_resolution import page, summary

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = summary()
            row["body"] = (
                row["body"]
                .replace("/805#", "/797#")
                .replace('"pullRequestNumber": 805', '"pullRequestNumber": 797')
            )
            (root / "comments.json").write_text(json.dumps(summary_pages([[row]])))
            (root / "threads.json").write_text(json.dumps([page()]))
            (root / "ci_codex_review_runtime.py").write_text(
                "raise RuntimeError('candidate runtime')"
            )
            result = self.run_gate(root, True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ready=true", (root / "output").read_text())

    def run_gate(self, root, completed, completion_only=False):
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
            '*reviewThreads*) cat "$FIXTURE/threads.json" ;; '
            '*graphql*) cat "$FIXTURE/comments.json" ;; '
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
                "CODEX_COMPLETION_ONLY": str(completion_only).lower(),
                "GITHUB_OUTPUT": str(root / "output"),
            },
            capture_output=True,
            text=True,
        )

    def seed_comments(self, root, completed):
        user = {
            "login": "chatgpt-codex-connector[bot]",
            "type": "Bot",
            "node_id": BOT_NODE_ID,
        }
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
                    "editor": None,
                    "lastEditedAt": None,
                    "body": body,
                }
            ]
        ]
        (root / "comments.json").write_text(json.dumps(summary_pages(comments)))

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
