"""A non-readiness merge failure must reach the real local repair queue."""

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_autopilot as runtime
from ci_autopilot_review import check
import ci_codex_reviews as reader
from tests_py.scripts.test_ci_codex_review_event_fixtures import (
    COMMENTS,
    DETAIL,
    REPO,
    SHA,
    Server,
    load,
)
from tests_py.scripts.test_ci_codex_reviews import OTHER


def merge_failure():
    server = Server()
    merge = next(job for job in server.data["jobs"] if job["name"] == "merge")
    # source: pipeline.yml merge job's actual eligibility step.
    merge["steps"] = [{"name": "Verify live PR eligibility", "conclusion": "failure"}]
    return server


class MergeRepair(unittest.TestCase):
    def tick(self, server):
        target, proofs = load(), []
        args = SimpleNamespace(repo=REPO, pr=797, sha=SHA)
        item = {
            "kind": "review_resume",
            "number": args.pr,
            "sha": SHA,
            "fingerprint": "failed",
        }

        def reconcile(options, selected):
            proof = check(args, target, reader)
            proofs.append(proof)
            return proof

        with (
            patch.dict(os.environ, {"EXPECTED_PR": str(args.pr)}),
            patch.object(target.source, "_api", side_effect=server),
            patch.object(reader, "_api", side_effect=server),
            patch.object(runtime, "snapshot", return_value=[item]),
            patch.object(runtime, "reconcile", side_effect=reconcile),
            patch.object(
                runtime, "launch", return_value={"state": "started"}
            ) as launch,
            patch.object(target, "_post") as post,
        ):
            result = runtime.tick(SimpleNamespace(inspect=False), {"seen": {}})
        post.assert_not_called()
        return result, proofs, launch.call_args_list

    def test_current_eligible_merge_infrastructure_failure_enters_repair(self):
        result, proofs, launches = self.tick(merge_failure())
        self.assertEqual(
            proofs, [{"action": "repair", "reason": "merge_infrastructure"}]
        )
        self.assertEqual(result, {"state": "started"})
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0].args[-1]["kind"], "pull")

    def test_current_hold_prevents_repair_before_reading_native_proof(self):
        server = merge_failure()
        server.data["pull"]["labels"] = [{"name": "hold"}]
        result, proofs, launches = self.tick(server)
        self.assertEqual(result["state"], "review_wait")
        self.assertEqual(proofs, [{"action": "none"}])
        self.assertEqual(launches, [])
        self.assertFalse(any(path == COMMENTS for path, _ in server.calls))

    def test_head_change_after_both_run_reads_cancels_repair(self):
        server, reads = merge_failure(), []

        def detail(_):
            if reads:
                server.data["pull"]["head"]["sha"] = OTHER
            reads.append("run-read")
            return server.data["source"]

        server.overrides[DETAIL] = detail
        result, proofs, launches = self.tick(server)
        self.assertEqual(len(reads), 2)
        self.assertEqual(result["state"], "review_wait")
        self.assertEqual(proofs, [{"action": "none"}])
        self.assertEqual(launches, [])

    def test_native_readiness_failure_still_waits_for_github(self):
        result, proofs, launches = self.tick(Server())
        self.assertEqual(result["state"], "review_wait")
        self.assertEqual(proofs, [{"action": "none"}])
        self.assertEqual(launches, [])
