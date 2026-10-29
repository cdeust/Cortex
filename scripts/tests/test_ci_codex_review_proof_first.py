"""Second native Claude review6459888424: cheap proof precedes REST discovery."""

import json
from itertools import product
import sys
import unittest
from unittest.mock import patch
import subprocess

from codex_resume_fixtures import SHA, comment, state
from test_ci_codex_review_event_fixtures import REPO, PULL, Server
import test_ci_codex_review_schedule as schedule
import test_ci_codex_review_reconcile as nullable
from test_ci_codex_review_resume import evidence


def missing(status="404"):
    return subprocess.CalledProcessError(
        1, ["gh", "api"], output=json.dumps(dict(status=status)), stderr="PRIVATE_TOKEN"
    )


def policy_route(server, route):
    if route == "green_wait":
        server.data["source"]["conclusion"] = "success"
        server.data["jobs"][-1].update(
            name="merge pending review",
            conclusion="success",
            steps=[
                dict(name="Record pending review", conclusion="success"),
                dict(name="Post cleanup", conclusion="skipped"),
            ],
        )
    elif route == "readiness":
        server.data["jobs"][1]["conclusion"] = "failure"
        server.data["jobs"][-2].update(
            conclusion="failure",
            steps=[dict(name="Require completed Codex reviews", conclusion="failure")],
        )


class ProofFirstTests(unittest.TestCase):
    def invoke(self, server, pages=None):
        return schedule.ScheduledReconciliationTests().invoke(server, pages)

    def test_incomplete_reviews_do_not_fetch_runs_or_jobs(self):
        for status in ("running", "failed"):
            server = Server()
            metadata = state()
            metadata["security_review"]["status"] = status
            server.data["comments"] = [comment(metadata)]
            result = self.invoke(server)
            self.assertEqual(json.loads(result[1]), [])
            self.assertFalse(any(path.startswith("repos/") for path, _ in server.calls))

    def test_successful_review_with_unresolved_proof_uses_no_rest(self):
        server = nullable.ReconciliationTests().server()
        server.data["threads"] = nullable.threads(resolved=False)
        result = self.invoke(server)
        self.assertEqual(json.loads(result[1]), [])
        self.assertFalse(any(path.startswith("repos/") for path, _ in server.calls))

    def test_unresolved_proof_still_allows_actual_failed_test_readiness_repair(self):
        server = nullable.ReconciliationTests().server()
        server.data["threads"] = nullable.threads(resolved=False)
        server.data["jobs"][1]["conclusion"] = "failure"
        server.data["jobs"][-2].update(
            conclusion="failure",
            steps=[dict(name="Require completed Codex reviews", conclusion="failure")],
        )
        result = self.invoke(server)
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])
        self.assertIn((PULL, False), server.calls)

    def test_all_policy_routes_discovered_for_clean_and_unresolved_proof(self):
        routes = ("green_wait", "readiness", "failed_merge")
        for route, unresolved in product(routes, (False, True)):
            with self.subTest(route=route, unresolved=unresolved):
                self.check_policy_route(route, unresolved)

    def check_policy_route(self, route, unresolved):
        target = schedule.load()
        server = nullable.ReconciliationTests().server()
        server.data["threads"] = nullable.threads(resolved=not unresolved)
        policy_route(server, route)
        proof = evidence("blocked" if unresolved else "success")
        actions = {
            "green_wait": ("review", "review"),
            "readiness": ("review", "review"),
            "failed_merge": ("merge", "none"),
        }
        expected_action = actions[route][unresolved]
        plan = target.events._plan(
            server.data["source"], server.data["jobs"], proof, SHA
        )
        self.assertEqual(plan["action"], expected_action)
        result = self.invoke(server)
        self.assertEqual(result[0], 0, result[2])
        expected = [] if expected_action == "none" else [dict(number=797, sha=SHA)]
        self.assertEqual(json.loads(result[1]), expected)
        self.assertEqual(result[4], [])
        if expected_action == "none":
            self.assertFalse(any(path.startswith("repos/") for path, _ in server.calls))

    def test_known_missing_pr_does_not_starve_next_pr(self):
        server = Server()
        row = schedule.discovery_node(server, server.data["pull"])
        row["number"] = 798
        schedule.load()
        # Use the reader's public catch boundary, not a policy mock.
        reader = sys.modules["ci_codex_reviews"]

        def known_missing(count):
            raise reader.APIError("not_found")

        server.overrides[f"repos/{REPO}/pulls/798"] = known_missing
        result = self.invoke(server, [[row, server.data["pull"]]])
        self.assertEqual(result[0], 0, result[2])
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])
        self.assertEqual(result[4], [])

    def test_partial_rollup_success_cannot_veto_actual_readiness_repair(self):
        server = nullable.ReconciliationTests().server()
        server.data["threads"] = nullable.threads(resolved=False)
        row = schedule.discovery_node(server, server.data["pull"])
        contexts = row["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]
        contexts["pageInfo"]["hasNextPage"] = True
        server.data["jobs"][1]["conclusion"] = "failure"
        server.data["jobs"][-2].update(
            conclusion="failure",
            steps=[dict(name="Require completed Codex reviews", conclusion="failure")],
        )
        result = self.invoke(server, [[row]])
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])


class StructuredAPITests(unittest.TestCase):
    def call(self, response, *, reader=False):
        target = schedule.load()
        module = sys.modules[
            "ci_codex_reviews" if reader else "ci_codex_review_runtime"
        ]
        with patch.object(target.events.subprocess, "run", side_effect=response):
            with self.assertRaises(module.APIError) as raised:
                module._api("repos/owner/project/pulls/1")
        self.assertEqual(str(raised.exception), "api")
        self.assertNotIn("PRIVATE_TOKEN", repr(raised.exception))
        return raised.exception.category

    def test_actual_rest_error_schema_keeps_fixed_category_through_reader(self):
        for reader in (False, True):
            self.assertEqual(self.call(missing(), reader=reader), "not_found")
            paginated = missing()
            paginated.stdout = json.dumps([dict(status="404")])
            self.assertEqual(self.call(paginated, reader=reader), "not_found")
            self.assertEqual(self.call(missing("403"), reader=reader), "forbidden")
            self.assertEqual(self.call(missing("429"), reader=reader), "rate_limited")
            self.assertEqual(self.call(missing("503"), reader=reader), "unknown")

    def test_graphql_error_types_and_unknown_transport_are_conservative(self):
        for kind, expected in (
            ("NOT_FOUND", "not_found"),
            ("RATE_LIMITED", "rate_limited"),
        ):
            error = missing()
            error.stdout = json.dumps(
                dict(errors=[dict(type=kind, message="PRIVATE_TOKEN")])
            )
            self.assertEqual(self.call(error), expected)
        self.assertEqual(self.call(OSError("PRIVATE_TOKEN")), "unknown")

    def test_summary_callback_preserves_known_api_category(self):
        schedule.load()
        reader = sys.modules["ci_codex_reviews"]

        def request(*args, **kwargs):
            raise reader.APIError("not_found")

        with self.assertRaises(reader.APIError) as caught:
            reader.summary_comments(REPO, 797, SHA, request)
        self.assertEqual(caught.exception.category, "not_found")

    def test_nullable_resolution_api_category_survives_normalized_proof(self):
        target = schedule.load()
        server = nullable.ReconciliationTests().server()
        runtime = sys.modules["ci_codex_review_runtime"]
        with (
            patch.object(target.events.source, "_api", side_effect=server),
            patch.object(runtime, "_api", side_effect=runtime.APIError("not_found")),
        ):
            result = target.events.head_proof(REPO, 797, SHA)
        self.assertEqual(
            (result["reason"], result["api_category"]), ("api", "not_found")
        )

    def test_quota_failure_aborts_before_later_pr(self):
        schedule.load()
        reader = sys.modules["ci_codex_reviews"]
        server = Server()
        row = schedule.discovery_node(server, server.data["pull"])
        row["number"] = 798

        def quota(count):
            raise reader.APIError("rate_limited")

        server.overrides[f"repos/{REPO}/pulls/798"] = quota
        result = schedule.ScheduledReconciliationTests().invoke(
            server, [[row, server.data["pull"]]]
        )
        self.assertEqual(result[0], 1)
        self.assertEqual(result[3], "")
        self.assertNotIn((PULL, False), server.calls)
        self.assertEqual(result[4], [])
