"""Native Codex finding4384655844: resolver retains previous attempt tests."""

import copy
import unittest

from tests_py.scripts.test_ci_review_required import resolver
from tests_py.scripts.test_ci_codex_review_event_fixtures import Server, source


class ResolverAttempts(unittest.TestCase):
    def test_a_merge_pending_review_job_is_no_merge_job(self):
        namespace = resolver()
        rows = copy.deepcopy(Server().data["jobs"])
        rows[-1].update(name="merge pending review", conclusion="success")
        with self.assertRaises(namespace["PostMergeError"]):
            namespace["_validate_jobs"](rows)

    def test_the_merge_aggregate_decides_whatever_the_review_did(self):
        namespace = resolver()
        rows = copy.deepcopy(Server().data["jobs"])
        rows[-1]["conclusion"] = "success"
        next(row for row in rows if row["name"] == "review")["conclusion"] = "failure"
        namespace["_validate_jobs"](rows)
        rows[0]["conclusion"] = "failure"
        with self.assertRaises(namespace["PostMergeError"]):
            namespace["_validate_jobs"](rows)

    def test_effective_graph_retains_tests_and_supersedes_old_gates(self):
        namespace = resolver()
        server = Server()
        run = source()
        run.update(run_attempt=2, conclusion="success")
        old = copy.deepcopy(server.data["jobs"])
        latest = copy.deepcopy(old[-2:])
        for row in latest:
            row.update(id=row["id"] + 100, run_attempt=2, conclusion="success")
        effective = namespace["_effective_jobs"](old + latest, run)
        namespace["_validate_jobs"](effective)
        self.assertEqual(len(effective), len(old))

    def test_same_attempt_duplicate_or_foreign_identity_is_rejected(self):
        namespace = resolver()
        server = Server()
        run = source()
        rows = server.data["jobs"]
        for field, value in [
            ("run_id", 999),
            ("head_sha", "b" * 40),
            ("run_attempt", 0),
        ]:
            malformed = copy.deepcopy(rows)
            malformed[0][field] = value
            with (
                self.subTest(field=field),
                self.assertRaises(namespace["PostMergeError"]),
            ):
                namespace["_effective_jobs"](malformed, run)
        with self.assertRaises(namespace["PostMergeError"]):
            namespace["_effective_jobs"]([*rows, rows[0]], run)
