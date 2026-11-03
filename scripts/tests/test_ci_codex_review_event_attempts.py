# source: https://github.com/cdeust/Cortex/blob/f4831d159c181b5e170c984f703ed733819f188e/tests_py/scripts/test_ci_codex_review_event_attempts.py
"""Partial reruns retain untouched prerequisites and supersede old outcomes."""

import copy
import unittest

from test_ci_codex_review_event_fixtures import (
    DETAIL,
    JOBS,
    Server,
    invoke,
)


def attempts(server, current):
    """Serve attempt-specific paginated jobs rather than an aggregate fiction."""
    server.data["source"]["run_attempt"] = len(current)
    for number, rows in enumerate(current, 1):
        values = copy.deepcopy(rows)
        for job in values:
            job["run_attempt"] = number
            if number > 1:
                job["id"] += number * 100
        endpoint = DETAIL + f"/attempts/{number}/jobs"
        server.overrides[endpoint] = lambda count, rows=values: [
            {"total_count": len(rows), "jobs": rows}
        ]


def partial(server):
    return [job for job in server.data["jobs"] if job["name"] in ("review", "merge")]


def pending_rerun(server):
    """Review API failure, then rerun failed jobs while reviews remain pending.

    Source: cortex-vision PR5 discussion_r4408735600 and pipeline.yml merge.name.
    """
    first = copy.deepcopy(server.data["jobs"])
    first[-2].update(
        conclusion="failure",
        steps=[{"name": "Require completed Codex reviews", "conclusion": "failure"}],
    )
    first[-1]["steps"] = [
        {"name": "Require completed tests and review", "conclusion": "failure"}
    ]
    current = partial(server)
    current[-1].update(name="merge pending review", conclusion="success", steps=[])
    server.data["source"]["conclusion"] = "success"
    return first, current


class PartialAttempts(unittest.TestCase):
    def test_pending_merge_supersedes_failed_merge_display_name(self):
        server = Server()
        first, current = pending_rerun(server)
        current_only = Server()
        current_only.data["jobs"] = [*first[:-2], *copy.deepcopy(current)]
        current_only.data["source"]["conclusion"] = "success"
        baseline, baseline_post = invoke(current_only)
        self.assertEqual(baseline, {"action": "review", "job_id": 20})
        self.assertEqual(len(baseline_post), 1)
        attempts(server, [first, current])
        result, post = invoke(server)
        self.assertEqual(result, {"action": baseline["action"], "job_id": 220})
        self.assertEqual(len(post), 1)

    def test_new_failed_merge_supersedes_old_pending_merge(self):
        server = Server()
        first, current = pending_rerun(server)
        first[-1].update(name="merge pending review", conclusion="success", steps=[])
        current[-1].update(
            name="merge", conclusion="failure",
            steps=[{"name": "Merge pull request", "conclusion": "failure"}],
        )
        server.data["source"]["conclusion"] = "failure"
        attempts(server, [first, current])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_new_waiting_merge_remains_the_rerun_target(self):
        server = Server()
        first, current = pending_rerun(server)
        first[-1].update(name="merge pending review", conclusion="success", steps=[])
        current[-1] = copy.deepcopy(Server().data["jobs"][-1])
        server.data["source"]["conclusion"] = "failure"
        attempts(server, [first, current])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "merge", "job_id": 221})
        self.assertEqual(len(post), 1)

    def test_pending_merge_does_not_hide_other_historical_failures(self):
        server = Server()
        first, current = pending_rerun(server)
        extra = copy.deepcopy(first[0])
        extra.update(id=99, name="other", conclusion="failure")
        attempts(server, [[*first, extra], current])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_merge_aliases_in_same_attempt_cannot_hide_failure(self):
        server = Server()
        first, current = pending_rerun(server)
        duplicate = copy.deepcopy(first[-1])
        duplicate["id"] = 99
        attempts(server, [first, [*current, duplicate]])
        with self.assertRaisesRegex(ValueError, "protocol"):
            invoke(server)

    def test_partial_review_rerun_retains_prior_successful_prerequisites(self):
        server = Server()
        first = copy.deepcopy(server.data["jobs"])
        first[-2].update(conclusion="failure")
        attempts(server, [first, partial(server)])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "merge", "job_id": 221})
        self.assertEqual(len(post), 1)

    def test_new_success_supersedes_old_failure(self):
        server = Server()
        first = copy.deepcopy(server.data["jobs"])
        first[0]["conclusion"] = "failure"
        attempts(server, [first, [server.data["jobs"][0], *partial(server)]])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "merge", "job_id": 221})
        self.assertEqual(len(post), 1)

    def test_new_matrix_children_supersede_old_skipped_placeholders(self):
        # Native review finding4384491846: job-level if precedes matrix expansion.
        server = Server()
        current = copy.deepcopy(server.data["jobs"])
        current[-2].update(
            conclusion="failure",
            steps=[
                {"name": "Require completed Codex reviews", "conclusion": "failure"}
            ],
        )
        first = [
            job
            for job in copy.deepcopy(current)
            if not job["name"].startswith(("environment (", "install ("))
        ]
        first[0]["conclusion"] = "failure"
        for identity, name in ((90, "environment"), (91, "install")):
            placeholder = copy.deepcopy(first[0])
            placeholder.update(id=identity, name=name, conclusion="skipped")
            first.append(placeholder)
        attempts(server, [first, current])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "review", "job_id": 220})
        self.assertEqual(len(post), 1)

    def test_older_target_is_never_rerun(self):
        server = Server()
        attempts(server, [server.data["jobs"], [server.data["jobs"][0]]])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_new_failure_supersedes_old_success(self):
        server = Server()
        current = [copy.deepcopy(server.data["jobs"][0]), *partial(server)]
        current[0]["conclusion"] = "failure"
        attempts(server, [server.data["jobs"], current])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_old_unrelated_failure_cannot_disappear_from_effective_graph(self):
        server = Server()
        first = copy.deepcopy(server.data["jobs"])
        extra = copy.deepcopy(first[0])
        extra.update(id=99, name="other", conclusion="failure")
        first.append(extra)
        attempts(server, [first, partial(server)])
        result, post = invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_untouched_success_can_survive_multiple_partial_attempts(self):
        server = Server()
        attempts(
            server, [server.data["jobs"], [server.data["jobs"][-2]], partial(server)]
        )
        result, post = invoke(server)
        self.assertEqual(result, {"action": "merge", "job_id": 321})
        self.assertEqual(len(post), 1)

    def test_history_identity_and_pagination_are_authenticated(self):
        for field, value in (
            ("run_attempt", 2),
            ("run_id", 99),
            ("head_sha", "b" * 40),
        ):
            server = Server()
            attempts(server, [server.data["jobs"], partial(server)])
            broken = copy.deepcopy(server.data["jobs"])
            broken[0][field] = value
            server.overrides[JOBS] = lambda count, rows=broken: [
                {"total_count": len(rows), "jobs": rows}
            ]
            with self.assertRaisesRegex(ValueError, "protocol"):
                invoke(server)
        server = Server()
        attempts(server, [server.data["jobs"], partial(server)])
        server.overrides[JOBS] = lambda count: [{"total_count": 1, "jobs": []}]
        with self.assertRaisesRegex(ValueError, "protocol"):
            invoke(server)

    def test_paginated_history_preserves_all_prerequisites(self):
        server = Server()
        attempts(server, [server.data["jobs"], partial(server)])
        rows = server.data["jobs"]
        server.overrides[JOBS] = lambda count: [
            {"total_count": len(rows), "jobs": rows[:1]},
            {"total_count": len(rows), "jobs": rows[1:]},
        ]
        result, post = invoke(server)
        self.assertEqual(result, {"action": "merge", "job_id": 221})
        self.assertEqual(len(post), 1)

    def test_historical_prerequisite_is_reread_before_post(self):
        server = Server()
        attempts(server, [server.data["jobs"], partial(server)])
        changed = copy.deepcopy(server.data["jobs"])
        changed[0]["conclusion"] = "failure"
        server.overrides[JOBS] = lambda count: [
            {
                "total_count": len(changed),
                "jobs": server.data["jobs"] if count == 1 else changed,
            }
        ]
        result, post = invoke(server)
        self.assertEqual(result, {"action": "none"})
        self.assertEqual(post, [])

    def test_same_job_identity_cannot_claim_two_attempts(self):
        server = Server()
        attempts(server, [server.data["jobs"], partial(server)])
        repeated = copy.deepcopy(server.data["jobs"][-2:])
        for job in repeated:
            job["run_attempt"] = 2
        server.overrides[DETAIL + "/attempts/2/jobs"] = lambda count: [
            {"total_count": len(repeated), "jobs": repeated}
        ]
        with self.assertRaisesRegex(ValueError, "protocol"):
            invoke(server)

    def test_duplicate_job_name_cannot_hide_failure(self):
        server = Server()
        current = partial(server)
        duplicate = copy.deepcopy(current[0])
        duplicate.update(id=99, conclusion="failure")
        attempts(server, [server.data["jobs"], [*current, duplicate]])
        with self.assertRaisesRegex(ValueError, "protocol"):
            invoke(server)


if __name__ == "__main__":
    unittest.main()
