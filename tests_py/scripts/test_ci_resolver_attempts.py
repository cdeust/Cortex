"""Native Codex finding4384655844: resolver retains previous attempt tests."""

import copy
import unittest
from unittest.mock import Mock

from tests_py.scripts.test_ci_review_required import resolver
from tests_py.scripts.test_ci_codex_review_event_fixtures import Server, source


class ResolverAttempts(unittest.TestCase):
    def test_pending_resolver_returns_without_any_merge_api_mutation(self):
        namespace = resolver()
        server = Server()
        run = server.data["source"]
        run["conclusion"] = "success"
        server.data["jobs"][-1].update(
            name="merge pending review", conclusion="success"
        )
        api = Mock()
        api.request.side_effect = lambda method, path: server(path.lstrip("/"))
        api.records.return_value = server.data["jobs"]
        result = namespace["resolve"](
            {"repository": {"full_name": "cdeust/Cortex"}, "workflow_run": run},
            "cdeust/Cortex",
            api,
        )
        self.assertEqual(result["run_tests"], "false")
        self.assertIn("pending", result["reason"])
        self.assertTrue(api.request.call_args_list)
        self.assertTrue(
            all(call.args[0] == "GET" for call in api.request.call_args_list)
        )

    def test_pending_review_validates_tests_without_authorizing_merge(self):
        namespace = resolver()
        rows = copy.deepcopy(Server().data["jobs"])
        rows[-1].update(name="merge pending review", conclusion="success")
        self.assertTrue(namespace["_validate_jobs"](rows, "cdeust"))
        rows[0]["conclusion"] = "failure"
        with self.assertRaises(namespace["PostMergeError"]):
            namespace["_validate_jobs"](rows, "cdeust")

    def test_completed_review_supersedes_the_prior_pending_job_name(self):
        namespace = resolver()
        rows = copy.deepcopy(Server().data["jobs"])
        rows[-1]["conclusion"] = "success"
        rows.append({**rows[-1], "name": "merge pending review"})
        self.assertFalse(namespace["_validate_jobs"](rows, "cdeust"))

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
        namespace["_validate_jobs"](effective, "cdeust")
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
