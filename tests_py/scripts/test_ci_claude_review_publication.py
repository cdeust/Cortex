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
    def check(self, rows, body, run=str(RUN), attempt="1"):
        server = Server()
        server.data["reviews"] = rows
        target = load(CLAUDE, "claude_event_publication")
        with tempfile.TemporaryDirectory() as directory:
            verdict = Path(directory) / "code-review.md"
            if body is not None:
                verdict.write_text(body)
            environ = {
                "PR": "797",
                "HEAD_SHA": SHA,
                "GITHUB_RUN_ID": run,
                "GITHUB_RUN_ATTEMPT": attempt,
                "REVIEW_FILE": str(verdict),
            }
            with patch.object(target.source, "_api", side_effect=server):
                target.published(REPO, "code", environ)

    def test_the_attempt_published_exactly_its_verdict(self):
        mine = review("code")
        self.check([mine, review("security", 0, 2)], mine["body"] + "\n")

    def test_unbound_or_other_attempt_markers_do_not_fail_this_attempt(self):
        # msg_037967ba0159: an @claude marker or a stale attempt's marker is not
        # this attempt's evidence, so it neither satisfies nor fails it.
        mine = review("code")
        others = [
            review("code", 0, 7, run="901-1"),
            review("code", 0, 8, run=f"{RUN}-2"),
            review("code", 0, 9, body="<!-- claude-review:v1 kind=code findings=0 -->"),
        ]
        self.check([*others, mine], mine["body"])

    def test_missing_altered_or_duplicated_publication_fails(self):
        mine = review("code")
        for rows, body, attempt in (
            ([], mine["body"], "1"),
            ([mine], mine["body"] + "\nedited", "1"),
            ([mine], mine["body"], "2"),
            ([mine, review("code", 0, 9)], mine["body"], "1"),
            ([review("code", commit_id="b" * 40)], mine["body"], "1"),
            ([mine], "", "1"),
        ):
            with (
                self.subTest(rows=rows, attempt=attempt),
                self.assertRaisesRegex(Exception, "^unpublished$"),
            ):
                self.check(rows, body, attempt=attempt)

    def test_absent_verdict_file_fails_closed(self):
        # The trusted step pre-creates the file; if Claude never wrote it, or it
        # vanished, there is no execution evidence.
        with self.assertRaises(FileNotFoundError):
            self.check([review("code")], None)


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
