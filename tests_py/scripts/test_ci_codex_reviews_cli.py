"""Authenticated gh-boundary and CLI privacy behavior for native Codex evidence."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests_py.scripts.test_ci_codex_reviews import (
    SHA,
    OTHER,
    SCRIPT,
    comment,
    module,
    pull,
    state,
)


class CodexCliTests(unittest.TestCase):
    def test_cli_rejects_invalid_sha_before_any_api(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo",
                "cdeust/Cortex",
                "--pr",
                "797",
                "--sha",
                "PRIVATE_TOKEN",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("PRIVATE_TOKEN", result.stderr)

    def invoke(self, payloads, extra=None):
        target = module()
        out = io.StringIO()
        err = io.StringIO()
        replies = [
            subprocess.CompletedProcess([], 0, json.dumps(value), "")
            for value in payloads
        ]
        with (
            patch.object(target.subprocess, "run", side_effect=replies) as api,
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = target.main(
                ["--repo", "cdeust/Cortex", "--pr", "797", "--sha", SHA, *(extra or [])]
            )
        return code, out.getvalue(), err.getvalue(), api.call_args_list

    def test_success_reads_all_comment_pages_and_checks_head_twice(self):
        stale = comment(state(OTHER))
        current = comment(comment_id=2, updated="2026-10-26T22:01:00Z")
        code, out, err, calls = self.invoke([pull(), [[stale], [current]], pull()])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["comment_id"], 2)
        self.assertEqual(len(calls), 3)
        self.assertIn("--paginate", calls[1].args[0])
        self.assertIn("--slurp", calls[1].args[0])
        for call in calls:
            self.assertIsInstance(call.args[0], list)
            self.assertFalse(call.kwargs.get("shell", False))

    def test_pending_exit_is_two(self):
        code, out, err, _ = self.invoke([pull(), [[]], pull()])
        self.assertEqual(code, 2, err)
        self.assertEqual(json.loads(out)["state"], "pending")

    def test_changed_head_after_comment_read_blocks(self):
        changed = pull()
        changed["head"]["sha"] = OTHER
        code, out, err, _ = self.invoke([pull(), [[comment()]], changed])
        self.assertEqual(code, 1)
        self.assertNotIn('"state": "success"', out)
        self.assertIn("head", err)

    def test_ineligible_pr_variants_block_before_comment_read(self):
        for mutate in (
            lambda p: p.update(state="closed"),
            lambda p: p.update(draft=True),
            lambda p: p["base"].update(ref="develop"),
            lambda p: p["head"]["repo"].update(full_name="other/Fork"),
            lambda p: p["head"].update(sha=OTHER),
        ):
            item = pull()
            mutate(item)
            code, out, err, calls = self.invoke([item])
            self.assertEqual(code, 1)
            self.assertEqual(len(calls), 1)

    def test_api_failure_and_malformed_pagination_do_not_leak_stderr(self):
        target = module()
        err = io.StringIO()
        with (
            patch.object(
                target.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(
                    1, ["gh"], stderr="PRIVATE_TOKEN"
                ),
            ),
            contextlib.redirect_stderr(err),
        ):
            code = target.main(["--repo", "cdeust/Cortex", "--pr", "797", "--sha", SHA])
        self.assertEqual(code, 1)
        self.assertNotIn("PRIVATE_TOKEN", err.getvalue())
        code, out, err, _ = self.invoke([pull(), {"PRIVATE_TOKEN": "bad"}])
        self.assertEqual(code, 1)
        self.assertNotIn("PRIVATE_TOKEN", out + err)

    def test_shell_and_output_injection_inputs_are_rejected_without_api(self):
        for flag, value in (
            ("--repo", "cdeust/Cortex\nready=true"),
            ("--repo", "x/../other"),
            ("--repo", "$(touch x)/repo"),
            ("--pr", "0"),
            ("--pr", "-1"),
            ("--sha", SHA + "\nready=true"),
        ):
            target = module()
            err = io.StringIO()
            args = ["--repo", "cdeust/Cortex", "--pr", "797", "--sha", SHA]
            args[args.index(flag) + 1] = value
            with (
                patch.object(target.subprocess, "run") as api,
                contextlib.redirect_stderr(err),
            ):
                code = target.main(args)
            self.assertEqual(code, 1)
            api.assert_not_called()
            self.assertNotIn(value, err.getvalue())

    def test_malformed_repository_identity_fails_without_traceback(self):
        for value in (None, False, 0, [], {}):
            item = pull()
            item["head"]["repo"]["full_name"] = value
            code, out, err, _ = self.invoke([item])
            self.assertEqual(code, 1)
            self.assertIn("pr_eligibility", err)

    def test_github_output_contains_only_fixed_validated_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(path)}):
                code, _, err, _ = self.invoke(
                    [pull(), [[comment()]], pull()], ["--github-output"]
                )
            self.assertEqual(code, 0, err)
            self.assertEqual(
                path.read_text(),
                f"ready=true\nstate=success\nsha={SHA}\ncomment_id=1\n",
            )

    def test_complete_findings_can_reach_fix_without_passing_strict_gate(self):
        data = state()
        data["security_review"].update(
            has_any_findings=True, has_unresolved_findings=True
        )
        responses = [pull(), [[comment(data)]], pull()]
        strict, _, _, _ = self.invoke(responses)
        ready, out, err, _ = self.invoke(responses, ["--require-complete"])
        self.assertEqual(strict, 1)
        self.assertEqual(ready, 0, err)
        self.assertEqual(json.loads(out)["state"], "blocked")
        self.assertEqual(json.loads(out)["reason"], "review_unresolved")

    def test_require_complete_still_rejects_pending_failed_and_invalid_evidence(self):
        for status in ("running", "failed", "unknown"):
            data = state()
            data["security_review"]["status"] = status
            code, _, _, _ = self.invoke(
                [pull(), [[comment(data)]], pull()], ["--require-complete"]
            )
            self.assertEqual(code, 2 if status == "running" else 1)

    def test_completion_mode_preserves_strict_ready_output(self):
        data = state()
        data["code_review"].update(has_any_findings=True, has_unresolved_findings=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(path)}):
                code, _, err, _ = self.invoke(
                    [pull(), [[comment(data)]], pull()],
                    ["--require-complete", "--github-output"],
                )
            self.assertEqual(code, 0, err)
            self.assertIn("ready=false\nstate=blocked\n", path.read_text())

    def test_missing_github_output_is_blocked(self):
        with patch.dict(os.environ, {}, clear=True):
            code, out, err, _ = self.invoke(
                [pull(), [[comment()]], pull()], ["--github-output"]
            )
        self.assertEqual(code, 1)
        self.assertIn("output", err)


if __name__ == "__main__":
    unittest.main()
