"""A completed Codex review with a null verdict is requested once, then named.

Fixture: tests_py/scripts/fixtures/codex_null_verdict_ci_autonome_pr1.json,
two raw summaries of cdeust/ci-autonome#1 on one head (07:51:07Z after
"Draft marked ready", 07:57:01Z after "@codex security review").
"""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_autopilot_converge as cli  # noqa: E402
from ci_autopilot_converge_plan import plan, request_marker  # noqa: E402

EVIDENCE = json.loads(
    (
        Path(__file__).parent / "fixtures/codex_null_verdict_ci_autonome_pr1.json"
    ).read_text()
)
HEAD = EVIDENCE["head_sha"]
SUMMARY = "https://github.com/cdeust/ci-autonome/pull/1#issuecomment-6488058788"


def observation(sample: dict, requests: list) -> dict:
    pr = {"number": 1, "head": HEAD, "title": "t", "draft": False}
    pr.update(labels=["hold"], files=[], checks_completed=True)
    verdict = {"head": HEAD, "merge": True, "url": "u"}
    return {
        "pr": pr,
        "summary": sample["summary_comment"]["codex_review_state"],
        "summary_url": SUMMARY,
        "threads": [],
        "requests": requests,
        "claude": {"verdict": verdict, "check": None},
        "merge": None,
    }


class NullVerdictTests(unittest.TestCase):
    def test_first_null_verdict_requests_one_security_review_for_the_sha(self):
        result = plan(observation(EVIDENCE["samples"][0], []))
        self.assertEqual(
            [(a["type"], a["kind"], a["reason"]) for a in result["actions"]],
            [("request_review", "security_review", "unknown_verdict")],
        )
        body = result["actions"][0]["body"]
        self.assertTrue(body.startswith("@codex security review\n"))
        self.assertIn(request_marker("security_review", HEAD), body)
        self.assertEqual(result["causes"], [])

    def test_second_null_verdict_on_the_same_sha_is_named_with_the_summary(self):
        spent = [{"kind": "security_review", "head": HEAD}]
        result = plan(observation(EVIDENCE["samples"][1], spent))
        self.assertEqual(result["actions"], [])
        cause = f"codex_security_verdict_missing: {SUMMARY}"
        self.assertEqual(result["causes"], [cause])
        named = cli.name_requester(result, None)["causes"][0]
        self.assertTrue(named.startswith(cause))
        self.assertIn("CODEX_REQUEST_TOKEN unset", named)

    def test_the_hold_stays_while_a_verdict_is_missing(self):
        spent = [{"kind": "security_review", "head": HEAD}]
        result = plan(observation(EVIDENCE["samples"][1], spent))
        self.assertNotIn("remove_label", [a["type"] for a in result["actions"]])


if __name__ == "__main__":
    unittest.main()
