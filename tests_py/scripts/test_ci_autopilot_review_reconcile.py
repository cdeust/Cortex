"""Review-only waits must reuse trusted evidence instead of starting models."""

import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_autopilot as runtime
from ci_autopilot_queue import candidates
from ci_codex_review_resume import PREREQUISITES
from test_ci_autopilot import pull


def waiting():
    item = pull()
    item["statusCheckRollup"] = [
        *(
            {"name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}
            for name in PREREQUISITES
        ),
        {"name": "review", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {
            "name": "merge pending review",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
        },
    ]
    return item


class ReviewQueue(unittest.TestCase):
    def test_completed_review_wait_is_reconciled_instead_of_ignored(self):
        self.assertEqual(candidates([waiting()], [])[0]["kind"], "review_resume")

    def test_merge_failure_with_green_tests_is_reconciled_before_repair(self):
        item = waiting()
        item["statusCheckRollup"][-1] = {
            "name": "merge",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
        }
        self.assertEqual(candidates([item], [])[0]["kind"], "review_resume")

    def test_unrelated_failure_or_pending_never_enters_reconciliation(self):
        for conclusion in ("FAILURE", "CANCELLED", "TIMED_OUT"):
            item = waiting()
            item["statusCheckRollup"][0]["conclusion"] = conclusion
            self.assertEqual(candidates([item], [])[0]["kind"], "pull")
        for status in ("IN_PROGRESS", "REQUESTED", "WAITING"):
            item = waiting()
            item["statusCheckRollup"][0]["status"] = status
            self.assertEqual(candidates([item], []), [])

    def test_inspection_does_not_reconcile_and_wait_does_not_start_a_model(self):
        item = {
            "kind": "review_resume",
            "number": 12,
            "sha": "a" * 40,
            "fingerprint": "review-wait",
        }
        for inspect in (True, False):
            with (
                patch.object(runtime, "snapshot", return_value=[copy.deepcopy(item)]),
                patch.object(
                    runtime, "reconcile", return_value={"action": "none"}
                ) as resume,
                patch.object(runtime, "launch") as launch,
            ):
                result = runtime.tick(SimpleNamespace(inspect=inspect), {"seen": {}})
                launch.assert_not_called()
                self.assertEqual(resume.call_count, 0 if inspect else 1)
                self.assertEqual(result["state"], "ready" if inspect else "review_wait")

    def test_real_findings_can_repair_but_repeated_identical_snapshot_cannot(self):
        item = {
            "kind": "review_resume",
            "number": 12,
            "sha": "a" * 40,
            "fingerprint": "review-wait",
        }
        for seen in ({}, {"pull:12": "review-wait"}):
            with (
                patch.object(runtime, "snapshot", return_value=[copy.deepcopy(item)]),
                patch.object(runtime, "reconcile", return_value={"action": "repair"}),
                patch.object(
                    runtime, "launch", return_value={"state": "started"}
                ) as launch,
            ):
                runtime.tick(SimpleNamespace(inspect=False), {"seen": seen})
                self.assertEqual(launch.call_count, 0 if seen else 1)

    def test_waiting_review_does_not_starve_an_actionable_issue(self):
        wait = {
            "kind": "review_resume",
            "number": 12,
            "sha": "a" * 40,
            "fingerprint": "waiting",
        }
        issue = {"kind": "issue", "number": 13, "fingerprint": "approved"}
        with (
            patch.object(runtime, "snapshot", return_value=[wait, issue]),
            patch.object(runtime, "reconcile", return_value={"action": "none"}),
            patch.object(
                runtime, "launch", return_value={"state": "started"}
            ) as launch,
        ):
            self.assertEqual(
                runtime.tick(SimpleNamespace(inspect=False), {"seen": {}}),
                {"state": "started"},
            )
            self.assertEqual(launch.call_args.args[-1]["number"], 13)
