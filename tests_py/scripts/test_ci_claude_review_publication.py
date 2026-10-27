"""The review job's validation binds the published claude[bot] review to its run.

`ci_claude_review_event.py --published <kind>` runs as main's code right after
Claude: exactly one <kind> marker on the head, citing this run, whose body is the
verdict file this run wrote. Its success is what ci_claude_reviews.py attests.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests_py.scripts.test_ci_claude_review_event import CLAUDE, load
from tests_py.scripts.test_ci_claude_reviews import RUN, review
from tests_py.scripts.test_ci_codex_review_event_fixtures import REPO, SHA, Server


class PublicationTests(unittest.TestCase):
    def check(self, rows, body, run=str(RUN), kind="code"):
        server = Server()
        server.data["reviews"] = rows
        target = load(CLAUDE, "claude_event_publication")
        with tempfile.TemporaryDirectory() as directory:
            verdict = Path(directory) / f"{kind}-review.md"
            verdict.write_text(body)
            environ = {
                "PR": "797",
                "HEAD_SHA": SHA,
                "GITHUB_RUN_ID": run,
                "REVIEW_FILE": str(verdict),
            }
            with patch.object(target.source, "_api", side_effect=server):
                target.published(REPO, kind, environ)

    def test_the_run_published_exactly_its_verdict(self):
        mine = review("code")
        self.check([mine, review("security", 0, 2)], mine["body"] + "\n")

    def test_missing_altered_foreign_or_extra_marker_fails(self):
        mine = review("code")
        tag = review(
            "code", 0, 9, body=mine["body"].replace("findings=0", "findings=0 ")
        )
        for rows, body, run in (
            ([], mine["body"], str(RUN)),
            ([mine], mine["body"] + "\nedited", str(RUN)),
            ([mine], mine["body"], "901"),
            ([mine, review("code", 0, 9, run=901)], mine["body"], str(RUN)),
            ([mine, tag], mine["body"], str(RUN)),
            ([review("code", commit_id="b" * 40)], mine["body"], str(RUN)),
        ):
            with (
                self.subTest(rows=rows, run=run),
                self.assertRaisesRegex(Exception, "^unpublished$"),
            ):
                self.check(rows, body, run)


class CommandLineTests(unittest.TestCase):
    def test_other_events_write_empty_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            env = dict(os.environ, GITHUB_EVENT_NAME="issue_comment")
            env["GITHUB_OUTPUT"] = str(output)
            for flags in (["--target"], []):
                done = subprocess.run(
                    [sys.executable, str(CLAUDE), *flags],
                    env=env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(
                output.read_text(), "pr=\nsha=\ncode=false\nsecurity=false\n"
            )

    def test_unknown_arguments_fail(self):
        for flags in (["--publish"], ["--published"], ["--published", "code", "x"]):
            done = subprocess.run(
                [sys.executable, str(CLAUDE), *flags], text=True, capture_output=True
            )
            self.assertEqual(done.returncode, 1)
            self.assertIn("arguments", done.stderr)


if __name__ == "__main__":
    unittest.main()
