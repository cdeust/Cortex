"""Server transitions must cancel local repair even after clean initial proof."""

import copy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from ci_autopilot_review import check
import ci_codex_reviews as reader
from tests_py.scripts.test_ci_codex_review_event_fixtures import (
    COMMENTS,
    DETAIL,
    PREFIX,
    PULL,
    REPO,
    RUNS,
    SHA,
    Server,
    load,
)
from tests_py.scripts.test_ci_codex_reviews import OTHER, comment, state, summary_pages


class RepairRechecks(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        review = next(
            job for job in self.server.data["jobs"] if job["name"] == "review"
        )
        review.update(
            conclusion="failure",
            steps=[{"name": "Initialize review toolchain", "conclusion": "failure"}],
        )

    def invoke(self):
        target = load()
        args = SimpleNamespace(repo=REPO, pr=797, sha=SHA)
        with (
            patch.dict(os.environ, {"EXPECTED_PR": str(args.pr)}),
            patch.object(target.source, "_api", side_effect=self.server),
            patch.object(reader, "_api", side_effect=self.server),
            patch.object(target.subprocess, "run") as post,
        ):
            result = check(args, target, reader)
        post.assert_not_called()
        return result

    def test_new_latest_run_cancels_infrastructure_repair(self):
        original = self.server.data["source"]
        newer = {**original, "id": 51, "run_number": original["run_number"] + 1}
        self.server.overrides[RUNS] = lambda count: [
            {"total_count": 1, "workflow_runs": [original if count == 1 else newer]}
        ]
        self.server.overrides[PREFIX + "/actions/runs/51"] = lambda count: newer
        self.assertEqual(self.invoke(), {"action": "none"})

    def test_changed_attempt_cancels_infrastructure_repair(self):
        original = self.server.data["source"]
        newer = {**original, "run_attempt": original["run_attempt"] + 1}
        self.server.overrides[DETAIL] = lambda count: original if count == 1 else newer
        self.assertEqual(self.invoke(), {"action": "none"})

    def test_head_change_at_final_eligibility_read_cancels_infrastructure_repair(self):
        original = self.server.data["pull"]
        newer = copy.deepcopy(original)
        newer["head"]["sha"] = OTHER
        # source: check's initial live read + reader's two reads + latest's two
        # live reads precede repair_after_noop's final explicit eligibility read.
        self.server.overrides[PULL] = lambda count: original if count <= 5 else newer
        self.assertEqual(self.invoke(), {"action": "none"})

    def test_changed_authenticated_native_proof_cancels_infrastructure_repair(self):
        data = state()
        data["code_review"].update(has_any_findings=True, has_unresolved_findings=True)
        changed = comment(data, comment_id=9)
        changed.update(
            editor={
                "login": "chatgpt-codex-connector",
                "__typename": "Bot",
                "id": changed["user"]["node_id"],
            },
            lastEditedAt="2026-10-28T12:00:00Z",
            updated_at="2026-10-28T12:00:00Z",
        )
        original = self.server.data["comments"]
        self.server.overrides[COMMENTS] = lambda count: summary_pages(
            [original if count == 1 else [changed]], number=797, sha=SHA
        )
        self.assertEqual(self.invoke(), {"action": "none"})
