# source: https://github.com/cdeust/Cortex/blob/f4831d159c181b5e170c984f703ed733819f188e/tests_py/scripts/test_ci_codex_review_event_cli.py
"""Trusted identify mode and privacy-safe coordinator diagnostics."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_ci_codex_review_event_fixtures import (
    REPO,
    Server,
    event,
    load,
)


class EventCliTests(unittest.TestCase):
    def execute(self, payload, flags=None):
        target = load()
        server = Server()
        out = io.StringIO()
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "event"
            output = root / "output"
            path.write_text(json.dumps(payload))
            env = {
                "GITHUB_EVENT_NAME": "issue_comment",
                "GITHUB_EVENT_PATH": str(path),
                "GITHUB_REPOSITORY": REPO,
                "GH_TOKEN": "PRIVATE_TOKEN",
                "EXPECTED_PR": "797",
                "GITHUB_OUTPUT": str(output),
            }
            with (
                patch.dict(os.environ, env),
                patch.object(target.source, "_api", side_effect=server),
                patch.object(target.subprocess, "run") as post,
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                code = target.main([] if flags is None else flags)
            return (
                code,
                out.getvalue(),
                err.getvalue(),
                output.read_text() if output.exists() else "",
                post.call_args_list,
            )

    def test_identify_outputs_server_authenticated_pr_without_mutation(self):
        code, out, err, output, post = self.execute(event(), ["--identify"])
        self.assertEqual(code, 0, err)
        self.assertEqual(output, "pr=797\n")
        self.assertEqual(json.loads(out), {"pr": 797})
        self.assertEqual(post, [])

    def test_irrelevant_actor_identifies_empty_pr(self):
        payload = event()
        payload["sender"]["type"] = "User"
        code, _, err, output, post = self.execute(payload, ["--identify"])
        self.assertEqual(code, 0, err)
        self.assertEqual(output, "pr=\n")
        self.assertEqual(post, [])

    def test_resume_reauthenticates_event_independent_of_any_identify_output(self):
        payload = event()
        payload["sender"]["login"] = "human"
        code, out, err, _, post = self.execute(payload)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"action": "none"})
        self.assertEqual(post, [])

    def test_output_injection_arguments_are_rejected(self):
        code, out, err, _, post = self.execute(event(), ["--identify\npr=999"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertNotIn("pr=999", err)
        self.assertEqual(post, [])

    def test_protocol_and_api_errors_do_not_print_private_payload_or_stderr(self):
        target = load()
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event"
            path.write_text("{PRIVATE_TOKEN")
            env = {
                "GITHUB_EVENT_NAME": "issue_comment",
                "GITHUB_EVENT_PATH": str(path),
                "GITHUB_REPOSITORY": REPO,
                "GH_TOKEN": "PRIVATE_TOKEN",
                "EXPECTED_PR": "797",
            }
            with patch.dict(os.environ, env), contextlib.redirect_stderr(err):
                code = target.main([])
            self.assertEqual(code, 1)
            self.assertNotIn("PRIVATE_TOKEN", err.getvalue())
            path.write_text(json.dumps(event()))
            err = io.StringIO()
            with (
                patch.dict(os.environ, env),
                patch.object(
                    target.source, "_api", side_effect=target.EvidenceError("api")
                ),
                contextlib.redirect_stderr(err),
            ):
                code = target.main([])
            self.assertEqual(code, 1)
            self.assertIn("api", err.getvalue())
            self.assertNotIn("PRIVATE_TOKEN", err.getvalue())

    def test_post_failure_is_reported_without_raw_gh_stderr(self):
        target = load()
        server = Server()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {"EXPECTED_PR": "797"}),
            patch.object(target.source, "_api", side_effect=server),
            patch.object(
                target.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(
                    1, ["gh"], stderr="PRIVATE_TOKEN"
                ),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "^api$"):
                target.coordinate("issue_comment", event(), REPO)
        self.assertNotIn("PRIVATE_TOKEN", err.getvalue())


if __name__ == "__main__":
    unittest.main()
