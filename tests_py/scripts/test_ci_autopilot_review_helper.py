"""Trusted current-head proof controls local review resumption."""

import json
import os
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from ci_autopilot_review import check, reconcile


class ProofDecision(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(repo="cdeust/Cortex", pr=12, sha="a" * 40)
        self.event = SimpleNamespace(
            source=SimpleNamespace(
                live_pr=Mock(return_value={}), latest=Mock(return_value={})
            ),
            resume=Mock(return_value={"action": "merge", "job_id": 1}),
        )
        self.reader = SimpleNamespace(_fetch=Mock())

    def test_only_successful_current_authenticated_proof_can_resume(self):
        self.reader._fetch.return_value = {
            "sha": self.args.sha,
            "reviews_complete": True,
            "state": "success",
            "reason": "reviews_complete",
        }
        self.assertEqual(check(self.args, self.event, self.reader)["action"], "merge")
        self.event.resume.assert_called_once_with(
            "cdeust/Cortex", {"number": 12, "sha": self.args.sha, "run_id": None}
        )

    def test_pending_failed_protocol_or_stale_proof_never_resumes_or_repairs(self):
        for reason in ("review_missing", "review_pending", "review_failed", "protocol"):
            self.reader._fetch.return_value = {
                "sha": self.args.sha,
                "reviews_complete": False,
                "state": "blocked",
                "reason": reason,
            }
            expected = {"action": "none"}
            if reason == "protocol":
                expected["reason"] = "evidence_unverifiable"
            self.assertEqual(check(self.args, self.event, self.reader), expected)
        self.reader._fetch.return_value = {
            "sha": "b" * 40,
            "reviews_complete": True,
            "state": "success",
        }
        self.assertEqual(check(self.args, self.event, self.reader), {"action": "none"})
        self.event.resume.assert_not_called()

    def test_real_completed_findings_allow_repair_without_rerunning_reviews(self):
        self.reader._fetch.return_value = {
            "sha": self.args.sha,
            "reviews_complete": True,
            "state": "blocked",
            "reason": "review_unresolved",
        }
        self.assertEqual(
            check(self.args, self.event, self.reader), {"action": "repair"}
        )
        self.event.resume.assert_not_called()

    def test_closed_draft_held_or_moved_pull_does_not_read_proof(self):
        self.event.source.live_pr.return_value = None
        self.assertEqual(check(self.args, self.event, self.reader), {"action": "none"})
        self.reader._fetch.assert_not_called()

    def test_subprocess_binds_expected_pr_without_changing_supervisor_environment(self):
        before = dict(os.environ)
        options = SimpleNamespace(repository="cdeust/Cortex", repo=Path.cwd())
        item = {"number": 12, "sha": "a" * 40}
        done = subprocess.CompletedProcess([], 0, json.dumps({"action": "none"}), "")
        with patch("ci_autopilot_review.subprocess.run", return_value=done) as run:
            self.assertEqual(reconcile(options, item), {"action": "none"})
        self.assertEqual(run.call_args.kwargs["env"]["EXPECTED_PR"], "12")
        self.assertIn("-I", run.call_args.args[0])
        self.assertEqual(dict(os.environ), before)

    def unverifiable_output(self):
        import io
        import ci_autopilot_review as helper
        import ci_codex_review_event as event
        import ci_codex_reviews as reader

        output = io.StringIO()
        with (
            patch.dict(os.environ, {"EXPECTED_PR": "12"}),
            patch.object(reader, "_arguments", return_value=self.args),
            patch.object(event.source, "live_pr", return_value={}),
            patch.object(
                reader, "_fetch", side_effect=reader.EvidenceError("protocol")
            ),
            patch.object(event, "resume") as resume,
            patch("sys.stdout", output),
            patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(helper.main(), 0)
        resume.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result, {"action": "none", "reason": "evidence_unverifiable"})
        return output.getvalue()

    def test_unverifiable_proof_does_not_starve_a_later_authorized_issue(self):
        import io
        import ci_autopilot as runtime
        import ci_autopilot_review as helper

        output = self.unverifiable_output()
        wait = {
            "kind": "review_resume",
            "number": 12,
            "sha": "a" * 40,
            "fingerprint": "waiting",
        }
        issue = {"kind": "issue", "number": 13, "fingerprint": "approved"}
        options = SimpleNamespace(
            inspect=False, repository="cdeust/Cortex", repo=Path.cwd()
        )
        done = subprocess.CompletedProcess([], 0, output, "")
        with (
            patch.object(runtime, "snapshot", return_value=[wait, issue]),
            patch.object(helper.subprocess, "run", return_value=done),
            patch.object(
                runtime, "launch", return_value={"state": "started"}
            ) as launch,
            patch("sys.stderr", io.StringIO()) as diagnostic,
        ):
            self.assertEqual(runtime.tick(options, {"seen": {}}), {"state": "started"})
        self.assertEqual(launch.call_args.args[-1]["number"], 13)
        self.assertIn("cdeust/Cortex#12", diagnostic.getvalue())

    def test_programming_errors_remain_visible(self):
        import ci_autopilot_review as helper
        import ci_codex_review_event as event
        import ci_codex_reviews as reader

        with (
            patch.dict(os.environ, {"EXPECTED_PR": "12"}),
            patch.object(reader, "_arguments", return_value=self.args),
            patch.object(event.source, "live_pr", return_value={}),
            patch.object(reader, "_fetch", side_effect=TypeError("programming error")),
        ):
            with self.assertRaisesRegex(TypeError, "programming error"):
                helper.main()
