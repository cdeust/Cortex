"""Same-head recovery after an attempt fails execution validation (msg_bf2bf23dfa88).

An attempt that published markers and then failed "Validate <kind> review
execution" is superseded by a later validated attempt on the same head; it must
neither suppress the retry nor poison the later evidence. Conflicts among
validated attempts still fail closed, and real findings are never overridden.
"""

from __future__ import annotations

import unittest

from tests_py.scripts.test_ci_claude_review_event import (
    call,
    gate,
    produced,
    requested,
    waiting,
)
from tests_py.scripts.test_ci_claude_reviews import RUN, TOKEN, module, producer, review
from tests_py.scripts.test_ci_codex_review_event_fixtures import (
    CLAUDE_RUN,
    REPO,
    Server,
)

RETRY = f"{RUN}-2"  # the owner's re-run of the same claude.yml run


def retried(server, **conclusions):
    """Attempt 2 of the producing run, with its own validation steps."""
    jobs = [producer(**conclusions)]
    server.overrides[CLAUDE_RUN + "/attempts/2/jobs"] = lambda count: [
        {"total_count": 1, "jobs": jobs}
    ]
    return server


class ReaderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.reader = module()

    def evidence(self, rows, jobs):
        return self.reader.review_evidence(rows, review()["commit_id"], jobs.get)

    def test_validated_retry_supersedes_the_failed_attempt(self):
        jobs = {TOKEN: producer(code="failure"), RETRY: producer()}
        rows = [review("code", 0, 1), review("security", 0, 2)]
        rows.append(review("code", 0, 3, run=RETRY))
        result = self.evidence(rows, jobs)
        self.assertEqual(
            (result["state"], result["reason"]), ("success", "reviews_complete")
        )
        self.assertEqual(
            (result["code"]["review_id"], result["code"]["run"]), (3, RETRY)
        )

    def test_only_failed_attempts_ask_for_a_retry(self):
        jobs = {TOKEN: producer(code="failure")}
        result = self.evidence([review("code", 0, 1)], jobs)
        self.assertEqual(result["code"]["state"], "failed")
        self.assertIs(result["code"].get("retry"), True)

    def test_later_zero_never_overrides_validated_findings(self):
        jobs = {TOKEN: producer(), RETRY: producer()}
        rows = [review("code", 2, 1), review("code", 0, 3, run=RETRY)]
        rows.append(review("security", 0, 2))
        result = self.evidence(rows, jobs)
        self.assertEqual(
            (result["state"], result["reason"]), ("blocked", "review_unresolved")
        )
        self.assertIsNone(result["code"].get("retry"))

    def test_two_reviews_of_one_validated_attempt_fail_without_retry(self):
        rows = [review("code", 0, 1), review("code", 0, 4), review("security", 0, 2)]
        result = self.evidence(rows, {TOKEN: producer()})
        self.assertEqual(result["code"]["state"], "failed")
        self.assertIsNone(result["code"].get("retry"))


class HandlerRecoveryTests(unittest.TestCase):
    def test_failed_attempt_requests_a_new_review_of_that_kind(self):
        server = produced(Server(), code="failure")
        server.data["reviews"] = [review("code", 0, 1), review("security", 0, 2)]
        result, _ = call(server, "targets", requested(), REPO)
        self.assertEqual((result["code"], result["security"]), ("true", "false"))

    def test_validated_retry_on_the_same_head_resumes_the_gate(self):
        server = retried(produced(waiting(gate(Server())), code="failure"))
        server.data["reviews"] = [
            review("code", 0, 1),
            review("security", 0, 2),
            review("code", 0, 3, run=RETRY),
        ]
        result, post = call(server, "resume", requested(), REPO)
        self.assertEqual(result, {"action": "review", "job_id": 20})
        self.assertEqual(len(post), 1)


if __name__ == "__main__":
    unittest.main()
