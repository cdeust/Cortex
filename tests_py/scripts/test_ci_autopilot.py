"""Local Codex automation queue policy and duplicate-dispatch prevention."""

import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_autopilot as runtime  # noqa: E402
from ci_autopilot_queue import candidates  # noqa: E402


def pull():
    return {
        "number": 12,
        "title": "Fix bug",
        "isDraft": False,
        "isCrossRepository": False,
        "headRefOid": "a" * 40,
        "headRefName": "fix/bug",
        "labels": [],
        "statusCheckRollup": [],
    }


class QueueTests(unittest.TestCase):
    def test_drafts_holds_and_cross_repository_pulls_are_excluded(self):
        for change in (
            {"isDraft": True},
            {"isCrossRepository": True},
            {"title": "Fix bug (do not merge)"},
            {"labels": [{"name": "hold"}]},
        ):
            with self.subTest(change=change):
                item = {**pull(), **change}
                self.assertEqual(candidates([item], []), [])

    def test_pending_checks_do_not_start_a_worker(self):
        for check in (
            {"name": "unit", "status": "IN_PROGRESS"},
            {"context": "external", "state": "PENDING"},
        ):
            item = pull()
            item["statusCheckRollup"] = [check]
            self.assertEqual(candidates([item], []), [])

    def test_successful_merge_gate_uses_protected_auto_merge(self):
        item = pull()
        item["statusCheckRollup"] = [{"name": "merge", "conclusion": "SUCCESS"}]
        self.assertEqual(candidates([item], [])[0]["kind"], "merge")
        item["statusCheckRollup"][0]["conclusion"] = "FAILURE"
        self.assertEqual(candidates([item], [])[0]["kind"], "pull")

    def test_new_head_or_result_changes_the_queue_fingerprint(self):
        original = pull()
        changed = copy.deepcopy(original)
        changed["headRefOid"] = "b" * 40
        self.assertNotEqual(candidates([original], []), candidates([changed], []))
        changed = copy.deepcopy(original)
        changed["statusCheckRollup"] = [{"name": "unit", "conclusion": "FAILURE"}]
        self.assertNotEqual(candidates([original], []), candidates([changed], []))

    def test_issue_intake_follows_pr_repairs(self):
        issue = {"number": 4, "title": "Bug", "labels": [], "updated_at": "now"}
        self.assertEqual(
            [i["kind"] for i in candidates([pull()], [issue])], ["pull", "issue"]
        )


class DispatchTests(unittest.TestCase):
    def test_unchanged_items_do_not_call_a_model(self):
        item = candidates([pull()], [])[0]
        state = {"seen": {"pull:12": item["fingerprint"]}}
        with (
            patch.object(runtime, "snapshot", return_value=[item]),
            patch.object(runtime, "launch") as launch,
        ):
            self.assertEqual(
                runtime.tick(SimpleNamespace(inspect=False), state), {"state": "idle"}
            )
            launch.assert_not_called()

    def test_live_worker_blocks_a_second_launch(self):
        active = {
            "kind": "pull",
            "number": 12,
            "dispatch": "dispatch-a",
            "fingerprint": "old",
        }
        state = {"run": "run-a", "active": active}
        with (
            patch.object(runtime, "snapshot", return_value=[]),
            patch.object(
                runtime,
                "workers",
                return_value=[{"dispatchId": "dispatch-a", "terminalState": "active"}],
            ),
            patch.object(runtime, "launch") as launch,
        ):
            self.assertEqual(
                runtime.tick(SimpleNamespace(inspect=False), state),
                {"state": "worker_active"},
            )
            launch.assert_not_called()

    def test_missing_worker_is_not_treated_as_exited(self):
        state = {"run": "run-a", "active": {"dispatch": "dispatch-a"}}
        with patch.object(runtime, "workers", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "unverifiable"):
                runtime.settle(None, state, [])

    def test_settlement_does_not_consume_a_new_pr_head(self):
        item = candidates([pull()], [])[0]
        state = {
            "run": "run-a",
            "seen": {},
            "active": {**item, "fingerprint": "old", "dispatch": "dispatch-a"},
        }
        with patch.object(
            runtime,
            "workers",
            return_value=[{"dispatchId": "dispatch-a", "terminalState": "released"}],
        ):
            self.assertTrue(runtime.settle(None, state, [item]))
        self.assertEqual(state["seen"]["pull:12"], "old")
        self.assertNotIn("active", state)


class OrcaReceiptTests(unittest.TestCase):
    def test_unknown_start_with_durable_dispatch_is_not_relaunched(self):
        # Native Orca receipt2026-10-27: exit1, ok=true, outcome_unknown,
        # dispatchId=ctx_c938a6352cfc; the worker later completed successfully.
        import json
        import subprocess

        receipt = {
            "ok": True,
            "result": {"state": "outcome_unknown", "dispatchId": "ctx-native"},
        }
        done = subprocess.CompletedProcess([], 1, json.dumps(receipt), "")
        options = SimpleNamespace(orca="/usr/local/bin/orca", repo=ROOT)
        with patch.object(runtime.subprocess, "run", return_value=done):
            self.assertEqual(
                runtime.orca(options, "orchestration", "worker-start"),
                receipt["result"],
            )
