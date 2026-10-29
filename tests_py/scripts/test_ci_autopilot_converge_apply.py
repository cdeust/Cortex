"""The converge CLI reads native markers and executes only planned actions."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_autopilot_converge as cli  # noqa: E402
import ci_autopilot_converge_observe as observer  # noqa: E402
from ci_autopilot_converge_plan import request_marker  # noqa: E402

HEAD = "e5117943a3d394f7028abc3b70d6573eb3f10948"  # PR 830 head before fe32c7d0.
STATE = (
    '<!-- codex-review-state:v1 {"code_review":{"commit_sha":"%s","status":"completed",'
    '"has_any_findings":false,"has_unresolved_findings":false}} -->'
)


def comment(login, body, identity=1, updated="2026-10-29T07:00:00Z"):
    kind = "Bot" if login.endswith("[bot]") else "User"
    user = {"login": login, "type": kind}
    return {"id": identity, "user": user, "body": body, "updated_at": updated}


class ParseTests(unittest.TestCase):
    def test_summary_is_read_only_from_the_native_bot(self):
        late = "2026-10-29T08:00:00Z"
        forged = comment("someone", STATE % ("f" * 40), 9, late)
        native = comment(observer.BOT, STATE % HEAD, 2)
        summary = observer.codex_summary([native, forged])
        self.assertEqual(summary["code_review"]["commit_sha"], HEAD)
        self.assertIsNone(observer.codex_summary([forged]))

    def test_claude_verdict_is_read_only_from_the_claude_bot(self):
        marker = (
            '<!-- claude-review-verdict:v1 {"head": "%s", "merge": true} -->' % HEAD
        )
        native = comment("claude[bot]", marker)
        found = observer._latest_marker([native], "claude[bot]", observer.VERDICT)
        self.assertEqual((found["head"], found["merge"]), (HEAD, True))
        forged = comment("cdeust", marker)
        self.assertIsNone(
            observer._latest_marker([forged], "claude[bot]", observer.VERDICT)
        )

    def test_spent_requests_are_read_from_markers(self):
        body = "@codex review\n\n" + request_marker("code_review", HEAD)
        self.assertEqual(
            observer.spent_requests([comment("cdeust", body)]),
            [{"kind": "code_review", "head": HEAD}],
        )

    def test_pending_checks_are_not_completed(self):
        done = [{"status": "COMPLETED"}, {"state": "SUCCESS"}]
        self.assertTrue(observer.checks_completed(done))
        self.assertFalse(observer.checks_completed([{"status": "IN_PROGRESS"}]))
        self.assertFalse(observer.checks_completed([{"state": "PENDING"}]))


class ApplyTests(unittest.TestCase):
    def result(self):
        body = "@codex review\n\n" + request_marker("code_review", HEAD) + "\n"
        request = {"type": "request_review", "kind": "code_review", "body": body}
        return {
            "pr": 830,
            "head": HEAD,
            "causes": ["codex_finding_open: u"],
            "actions": [
                {"type": "remove_label", "label": "autopilot:hold"},
                {**request, "reason": "behind"},
                {"type": "resolve_withdrawn", "thread": "PRRT_x", "body": "Withdrawn"},
                {"type": "rerun_job", "job": 77},
            ],
        }

    def test_actions_and_red_status_are_published(self):
        with patch.object(cli, "gh", return_value=None) as gh:
            cli.apply("cdeust/Cortex", self.result(), "request-token")
        calls = [c.args for c in gh.call_args_list]
        label = "repos/cdeust/Cortex/issues/830/labels/autopilot%3Ahold"
        self.assertIn(label, calls[0])
        self.assertEqual(calls[1][:2], ("pr", "comment"))
        self.assertEqual(gh.call_args_list[1].kwargs["token"], "request-token")
        self.assertTrue(gh.call_args_list[1].kwargs["stdin"].startswith("@codex"))
        self.assertIn("t=PRRT_x", calls[2])
        self.assertTrue(any("resolveReviewThread" in a for a in calls[3]))
        self.assertIn("repos/cdeust/Cortex/actions/jobs/77/rerun", calls[4])
        self.assertIn(f"repos/cdeust/Cortex/statuses/{HEAD}", calls[5])
        self.assertIn("state=failure", calls[5])
        self.assertIn("description=codex_finding_open: u", calls[5])

    def test_converging_pr_gets_a_green_status(self):
        quiet = {"pr": 1, "head": HEAD, "causes": [], "actions": []}
        with patch.object(cli, "gh", return_value=None) as gh:
            cli.apply("cdeust/Cortex", quiet, None)
        self.assertIn("state=success", gh.call_args_list[0].args)


if __name__ == "__main__":
    unittest.main()
