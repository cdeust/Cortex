"""The merge gate counts exact-commit claude[bot] code and security verdicts."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = (ROOT / ".github/workflows/pipeline.yml").read_text()
# Synthetic full SHA-1 values for fixtures.
SHA, OTHER = "a" * 40, "b" * 40


def gate_script():
    block = PIPELINE.split("      - name: Require complete Claude verdicts\n", 1)[1]
    block = block.split("\n      - name:", 1)[0]
    lines = block.split("        run: |\n", 1)[1].splitlines()
    return "\n".join(line[10:] for line in lines)


def review(kind, findings=0, state="COMMENTED", sha=SHA, login="claude[bot]"):
    marker = f"<!-- claude-review:v1 kind={kind} findings={findings} -->\nbody"
    return {
        "user": {"login": login, "type": "Bot"},
        "commit_id": sha,
        "state": state,
        "body": marker,
    }


class VerdictGateTests(unittest.TestCase):
    def run_gate(self, reviews):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fixture.json").write_text(json.dumps(reviews))
            gh = root / "gh"
            gh.write_text('#!/bin/sh\ncat "$FIXTURE/fixture.json"\n')
            gh.chmod(0o700)
            return subprocess.run(
                ["bash", "-c", gate_script()],
                env={
                    **os.environ,
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "FIXTURE": directory,
                    "RUNNER_TEMP": directory,
                    "GH_REPO": "cdeust/Cortex",
                    "PR": "797",
                    "HEAD_SHA": SHA,
                },
                capture_output=True,
                text=True,
            ).returncode

    def test_clean_code_and_security_verdicts_pass_for_commented_or_approved(self):
        for state in ("COMMENTED", "APPROVED"):
            with self.subTest(state=state):
                self.assertEqual(
                    self.run_gate([review("code", state=state), review("security")]), 0
                )

    def test_missing_wrong_commit_wrong_author_or_bad_state_blocks(self):
        for reviews in (
            [review("code")],
            [review("security")],
            [review("code", sha=OTHER), review("security")],
            [review("code"), review("security", login="github-actions[bot]")],
            [review("code"), review("security", state="CHANGES_REQUESTED")],
            [review("code"), review("security", state="DISMISSED")],
            [],
        ):
            with self.subTest(reviews=reviews):
                self.assertNotEqual(self.run_gate(reviews), 0)

    def test_findings_and_latest_verdict_decide(self):
        self.assertNotEqual(
            self.run_gate([review("code", findings=2), review("security")]), 0
        )
        self.assertNotEqual(
            self.run_gate([review("code"), review("security"), review("code", 1)]), 0
        )
        self.assertEqual(
            self.run_gate([review("code", 1), review("security"), review("code")]), 0
        )

    def test_unmarked_review_text_is_not_a_verdict(self):
        plain = review("code")
        plain["body"] = "LGTM, code and security are fine"
        self.assertNotEqual(self.run_gate([plain, review("security")]), 0)


if __name__ == "__main__":
    unittest.main()
