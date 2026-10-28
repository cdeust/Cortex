"""Fixed error categories preserve observability without leaking child stderr."""

import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_autopilot_review as helper
import ci_codex_review_event as event
import ci_codex_reviews as reader


class Diagnostics(unittest.TestCase):
    def invoke(self, error=None, expected="12"):
        output, diagnostic = io.StringIO(), io.StringIO()
        args = SimpleNamespace(repo="cdeust/Cortex", pr=12, sha="a" * 40)
        with (
            patch.dict(os.environ, {"EXPECTED_PR": expected}),
            patch.object(reader, "_arguments", return_value=args),
            patch.object(event.source, "live_pr", return_value={}) as live,
            patch.object(reader, "_fetch", side_effect=reader.EvidenceError(error)),
            patch.object(event, "resume") as resume,
            patch("sys.stdout", output),
            patch("sys.stderr", diagnostic),
        ):
            self.assertEqual(helper.main(), 0)
        resume.assert_not_called()
        return json.loads(output.getvalue()), diagnostic.getvalue(), live.call_count

    def test_known_failures_have_distinct_fixed_sanitized_categories(self):
        for error, category in (
            ("api", "api"),
            ("protocol", "protocol"),
            ("editor", "protocol"),
            ("environment", "environment"),
            ("head_moved", "eligibility"),
            ("unknown-private-token-value", "protocol"),
        ):
            with self.subTest(error=error):
                result, diagnostic, _ = self.invoke(error)
                self.assertEqual(
                    result,
                    {
                        "action": "none",
                        "reason": "evidence_unverifiable",
                        "category": category,
                    },
                )
                self.assertIn(category, diagnostic)
                self.assertNotIn("unknown-private-token-value", diagnostic)

    def test_expected_pr_mismatch_is_rejected_before_any_github_request(self):
        result, diagnostic, calls = self.invoke(expected="13")
        self.assertEqual(result["category"], "environment")
        self.assertIn("environment", diagnostic)
        self.assertEqual(calls, 0)

    def test_parent_keeps_category_without_forwarding_raw_child_stderr(self):
        result = {
            "action": "none",
            "reason": "evidence_unverifiable",
            "category": "api",
        }
        done = subprocess.CompletedProcess(
            [], 0, json.dumps(result), "private-token-value"
        )
        options = SimpleNamespace(repository="cdeust/Cortex", repo=Path.cwd())
        diagnostic = io.StringIO()
        with (
            patch.object(helper.subprocess, "run", return_value=done),
            patch("sys.stderr", diagnostic),
        ):
            self.assertEqual(
                helper.reconcile(options, {"number": 12, "sha": "a" * 40}), result
            )
        self.assertIn("api", diagnostic.getvalue())
        self.assertIn("cdeust/Cortex#12", diagnostic.getvalue())
        self.assertNotIn("private-token-value", diagnostic.getvalue())
