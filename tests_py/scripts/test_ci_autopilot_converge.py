"""Convergence planner: no PR waits for the owner (owner rules 2026-10-29).

Fixtures are the real API states of the PRs that stalled on 2026-10-29
(tests_py/scripts/fixtures/ci_autopilot_converge_prs.json).
"""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ci_autopilot_converge_plan import ELIGIBILITY_STEP, plan  # noqa: E402

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/ci_autopilot_converge_prs.json").read_text()
)["cases"]
UNREADABLE = (
    "claude_verdict_unreadable: no claude-review-verdict:v1 marker for this head"
)


def case(number, claude_merge=None):
    item = copy.deepcopy(FIXTURES[str(number)])
    if claude_merge is not None:
        url = f"https://github.com/cdeust/Cortex/pull/{number}#issuecomment-1"
        item["claude"]["verdict"] = {
            "head": item["pr"]["head"],
            "merge": claude_merge,
            "url": url,
        }
    return item


def kinds(result, action):
    return sorted(a.get("kind", "") for a in result["actions"] if a["type"] == action)


def converged(number):
    """The PR after both native reviews concluded clean on its head."""
    item = case(number, claude_merge=True)
    head = item["pr"]["head"]
    clean = {"commit_sha": head, "status": "completed", "has_any_findings": False}
    item["summary"] = {
        kind: {**clean, "has_unresolved_findings": False}
        for kind in ("code_review", "security_review")
    }
    item["threads"] = []
    return item


class TwoAgreementsTests(unittest.TestCase):
    def test_both_reviewers_agree_lifts_the_hold_and_reruns_the_held_merge(self):
        item = converged(830)
        item["pr"]["labels"] = ["hold", "autopilot:hold"]
        merge = {"run_id": 1, "job_id": 77, "rerun_job": 77}
        item["merge"] = {**merge, "failed_step": ELIGIBILITY_STEP}
        result = plan(item)
        self.assertEqual(result["causes"], [])
        self.assertEqual(
            result["actions"],
            [
                {"type": "remove_label", "label": "hold"},
                {"type": "remove_label", "label": "autopilot:hold"},
                {"type": "rerun_job", "job": 77},
            ],
        )

    def test_without_a_readable_claude_verdict_the_hold_stays_and_is_named(self):
        item = converged(830)
        item["claude"]["verdict"] = None
        item["pr"]["labels"] = ["hold"]
        result = plan(item)
        self.assertEqual(result["actions"], [])
        self.assertEqual(result["causes"], [UNREADABLE])


class MissingReviewerTests(unittest.TestCase):
    def test_pr830_codex_review_behind_head_is_requested(self):
        result = plan(case(830, claude_merge=True))
        self.assertEqual(kinds(result, "request_review"), ["code_review"])
        request = result["actions"][0]
        # Bare trigger: a trailing marker turned a security request into a code
        # review on #830 (08:16:09Z -> receipt 08:17:27Z).
        self.assertEqual(request["body"], "@codex review")
        self.assertEqual(request["context"], "autopilot-converge/request-code_review")
        self.assertEqual(request["reason"], "behind")

    def test_pr830_a_spent_request_becomes_a_named_red_cause(self):
        item = case(830, claude_merge=True)
        item["requests"] = [{"kind": "code_review", "head": item["pr"]["head"]}]
        result = plan(item)
        self.assertEqual(kinds(result, "request_review"), [])
        cause = "review_stale_after_request: code_review behind"
        self.assertIn(cause, result["causes"])

    def test_absent_codex_review_is_requested(self):
        for number in (772, 765):
            with self.subTest(number=number):
                result = plan(case(number, claude_merge=True))
                self.assertEqual(kinds(result, "request_review"), ["code_review"])
                self.assertEqual(result["actions"][0]["reason"], "absent")
                self.assertEqual(result["causes"], [])

    def test_codex_running_after_every_check_is_requested_else_waits(self):
        result = plan(case(828, claude_merge=True))
        self.assertEqual(result["actions"][0]["reason"], "running_after_checks")
        item = case(828, claude_merge=True)
        item["pr"]["checks_completed"] = False
        self.assertEqual(plan(item)["actions"], [])

    def test_absent_or_behind_review_waits_while_checks_run(self):
        for number in (830, 772):
            with self.subTest(number=number):
                item = case(number, claude_merge=True)
                item["pr"]["checks_completed"] = False
                self.assertEqual(plan(item)["actions"], [])

    def test_unknown_security_verdict_is_requested(self):
        result = plan(case(833))
        request = [a for a in result["actions"] if a["type"] == "request_review"]
        self.assertEqual([a["kind"] for a in request], ["security_review"])
        self.assertEqual(request[0]["body"], "@codex security review")

    def test_failed_claude_review_is_rerun_once_then_named(self):
        item = converged(830)
        failed = {"conclusion": "failure", "run_id": 5, "job_id": 9, "attempt": 1}
        item["claude"] = {"verdict": None, "check": failed}
        self.assertEqual(plan(item)["actions"], [{"type": "rerun_job", "job": 9}])
        item["claude"]["check"]["attempt"] = 2
        cause = "claude_review_failed_after_rerun: run 5"
        self.assertEqual(plan(item)["causes"], [cause])

    def test_claude_review_that_never_ran_is_named(self):
        item = converged(830)
        item["claude"] = {"verdict": None, "check": None}
        cause = "claude_review_absent: no Claude review run for this head"
        self.assertEqual(plan(item)["causes"], [cause])


if __name__ == "__main__":
    unittest.main()
