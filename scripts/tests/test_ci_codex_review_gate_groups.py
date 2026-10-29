"""Spec160 native Claude6460515146: names are hints, never a last-write veto."""

import copy
import json
import sys
import unittest
from itertools import product

from codex_resume_fixtures import SHA
from test_ci_codex_review_event_fixtures import Server
import test_ci_codex_review_schedule as schedule
import test_ci_codex_review_reconcile as nullable


def contexts(row):
    return row["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]


def readiness(server):
    server.data["jobs"][1]["conclusion"] = "failure"
    server.data["jobs"][-2].update(
        conclusion="failure",
        steps=[dict(name="Require completed Codex reviews", conclusion="failure")],
    )


class ProofErrorServer(Server):
    def __init__(self, category):
        super().__init__()
        self.category, self.proof_calls = category, 0

    def graphql(self, fields):
        if "reviewThreads(" not in fields["query"]:
            return super().graphql(fields)
        self.proof_calls += 1
        reader = sys.modules["ci_codex_reviews"]
        if self.category is None:
            raise reader.EvidenceError("api")
        raise reader.APIError(self.category)


class GateGroupTests(unittest.TestCase):
    def invoke(self, server, rows=None):
        return schedule.ScheduledReconciliationTests().invoke(server, rows)

    def test_duplicate_gate_states_never_veto_actual_plan(self):
        states = (
            ("COMPLETED", "SUCCESS"),
            ("QUEUED", None),
            ("COMPLETED", "CANCELLED"),
        )
        for gate, (status, conclusion) in product(("review", "merge"), states):
            server = Server()
            if gate == "review":
                readiness(server)
            row = schedule.discovery_node(server, server.data["pull"])
            contexts(row)["nodes"].append(
                dict(
                    __typename="CheckRun",
                    name=gate,
                    status=status,
                    conclusion=conclusion,
                )
            )
            result = self.invoke(server, [[row]])
            self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])

    def test_status_context_cannot_shadow_a_real_gate(self):
        for gate in ("review", "merge"):
            for state in ("PENDING", "EXPECTED", "SUCCESS"):
                server = Server()
                row = schedule.discovery_node(server, server.data["pull"])
                contexts(row)["nodes"].append(
                    dict(__typename="StatusContext", context=gate, state=state)
                )
                result = self.invoke(server, [[row]])
                self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])

    def test_failed_prerequisite_is_decided_by_the_actual_pipeline_policy(self):
        server = Server()
        server.data["jobs"][1]["conclusion"] = "failure"
        result = self.invoke(server)
        self.assertEqual(json.loads(result[1]), [])
        self.assertTrue(any("/attempts/" in path for path, _ in server.calls))

    def test_red_prerequisite_never_vetoes_readiness_or_partial_rollup(self):
        server = Server()
        readiness(server)
        self.assertEqual(
            json.loads(self.invoke(server)[1]), [dict(number=797, sha=SHA)]
        )
        server = Server()
        row = schedule.discovery_node(server, server.data["pull"])
        contexts(row)["nodes"][1]["conclusion"] = "FAILURE"
        contexts(row)["pageInfo"]["hasNextPage"] = True
        self.assertEqual(
            json.loads(self.invoke(server, [[row]])[1]), [dict(number=797, sha=SHA)]
        )

    def test_duplicate_prerequisite_cannot_turn_stale_failure_into_veto(self):
        server = Server()
        row = schedule.discovery_node(server, server.data["pull"])
        stale = copy.deepcopy(contexts(row)["nodes"][1])
        stale["conclusion"] = "FAILURE"
        contexts(row)["nodes"].append(stale)
        self.assertEqual(
            json.loads(self.invoke(server, [[row]])[1]), [dict(number=797, sha=SHA)]
        )

    def test_superseded_matrix_placeholder_cannot_veto_expanded_successes(self):
        server = Server()
        row = schedule.discovery_node(server, server.data["pull"])
        contexts(row)["nodes"].append(
            dict(
                __typename="CheckRun",
                name="environment",
                status="COMPLETED",
                conclusion="FAILURE",
            )
        )
        result = self.invoke(server, [[row]])
        self.assertEqual(json.loads(result[1]), [dict(number=797, sha=SHA)])

    def test_normalized_head_proof_api_errors_pass_through_discovery(self):
        schedule.load()
        for category in ("not_found", "forbidden", "rate_limited", "unknown", None):
            server = ProofErrorServer(category)
            server.data = nullable.ReconciliationTests().server().data
            result = self.invoke(server)
            self.assertEqual(server.proof_calls, 1)
            self.assertEqual(result[0], 0 if category == "not_found" else 1)
            self.assertEqual(result[4], [])
            self.assertFalse(any(path.startswith("repos/") for path, _ in server.calls))
