"""The merge gate waits for its Claude review run, then counts exact-commit verdicts."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = (ROOT / ".github/workflows/pipeline.yml").read_text()
CLAUDE = (ROOT / ".github/workflows/claude.yml").read_text()
# Synthetic full SHA-1 values and run id for fixtures.
SHA, OTHER, RUN = "a" * 40, "b" * 40, "4242"

# The fake gh answers only the four calls the gate makes. run list prints the Claude
# run id only when the title query names this pipeline run.
FAKE_GH = """#!/bin/sh
case "$1 $2" in
  "run list")
    case "$*" in
      *"Claude review of Pipeline run $GITHUB_RUN_ID"*) echo "$CLAUDE_RUN" ;;
    esac ;;
  "run watch") exit "$WATCH_RC" ;;
  "run view") echo "$CONCLUSION" ;;
  api*) cat "$FIXTURE/fixture.json" ;;
  *) echo "unexpected gh call: $*" >&2; exit 99 ;;
esac
"""


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
    def run_gate(self, reviews, run="99", watch=0, conclusion="success"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fixture.json").write_text(json.dumps(reviews))
            gh = root / "gh"
            gh.write_text(FAKE_GH)
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
                    "GITHUB_RUN_ID": RUN,
                    "CLAUDE_RUN": run,
                    "WATCH_RC": str(watch),
                    "CONCLUSION": conclusion,
                },
                capture_output=True,
                text=True,
            ).returncode

    def clean(self):
        return [review("code"), review("security")]

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

    def test_the_gate_waits_for_and_requires_its_own_successful_claude_run(self):
        # A late verdict must not strand the gate, and verdicts alone are not enough
        # when the run's execution validators failed (Codex 4384253238, 4384253243).
        self.assertNotEqual(self.run_gate(self.clean(), run=""), 0)
        self.assertNotEqual(self.run_gate(self.clean(), watch=1), 0)
        for conclusion in ("failure", "skipped", "cancelled"):
            with self.subTest(conclusion=conclusion):
                self.assertNotEqual(
                    self.run_gate(self.clean(), conclusion=conclusion), 0
                )

    def test_run_name_and_merge_permissions_match_the_gate(self):
        self.assertIn("format('Claude review of Pipeline run {0}'", CLAUDE)
        self.assertIn("github.event.workflow_run.id", CLAUDE.split("\n\n", 1)[0])
        merge = PIPELINE.split("\n  merge:\n", 1)[1].split("    steps:\n", 1)[0]
        self.assertIn("actions: read", merge)

    def test_bot_authored_repairs_can_trigger_the_reviews(self):
        # The Fix action pushes as claude[bot]; the action rejects bot actors that
        # allowed_bots does not list (Codex 4384253244).
        self.assertEqual(CLAUDE.count('allowed_bots: "claude[bot],'), 2)


if __name__ == "__main__":
    unittest.main()
