"""A reviewer refusal is fixed or named red; withdrawn findings and holds."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ci_autopilot_converge_plan import plan  # noqa: E402
from ci_autopilot_queue import candidates, held  # noqa: E402
from tests_py.scripts.test_ci_autopilot_converge import case, converged  # noqa: E402


class RefusalTests(unittest.TestCase):
    def test_open_codex_findings_are_named_and_keep_the_hold(self):
        for number in (826, 829):
            with self.subTest(number=number):
                item = case(number, claude_merge=True)
                result = plan(item)
                self.assertNotIn("remove_label", [a["type"] for a in result["actions"]])
                self.assertTrue(result["causes"])
                self.assertTrue(
                    all(c.startswith("codex_finding_open: ") for c in result["causes"])
                )

    def test_claude_refusal_is_named_and_keeps_the_hold(self):
        item = converged(830)
        item["claude"]["verdict"]["merge"] = False
        item["pr"]["labels"] = ["hold"]
        result = plan(item)
        self.assertEqual(result["actions"], [])
        self.assertEqual(
            result["causes"],
            [
                "claude_refused: https://github.com/cdeust/Cortex/pull/830#issuecomment-1"
            ],
        )

    def test_open_claude_inline_finding_is_a_refusal(self):
        item = case(833, claude_merge=True)
        claude = item["threads"][0]
        claude["path"] = item["pr"]["files"][0]
        result = plan(item)
        self.assertIn(f"claude_finding_open: {claude['url']}", result["causes"])

    def test_all_codex_findings_resolved_but_flag_still_true_requests_review(self):
        item = case(829, claude_merge=True)
        for thread in item["threads"]:
            thread["resolved"] = True
        result = plan(item)
        self.assertEqual(
            [a["reason"] for a in result["actions"] if a["type"] == "request_review"],
            ["findings_resolved_or_withdrawn"],
        )
        self.assertEqual(result["causes"], [])


class WithdrawnTests(unittest.TestCase):
    def test_codex_code_finding_on_a_withdrawn_path_is_answered_and_resolved(self):
        item = case(833)
        result = plan(item)
        resolved = [a for a in result["actions"] if a["type"] == "resolve_withdrawn"]
        # Claude inline findings carry no security marker: never auto-resolved.
        self.assertEqual([a["thread"] for a in resolved], ["PRRT_kwDORqU88s6xbcOL"])
        codex = [t for t in item["threads"] if t["reviewer"] == "codex"][0]
        self.assertIn(codex["path"], resolved[0]["body"])
        self.assertIn(item["pr"]["head"], resolved[0]["body"])

    def test_pr831_withdrawn_security_finding_requests_review_never_self_resolves(self):
        item = case(831, claude_merge=True)
        result = plan(item)
        requests = [a for a in result["actions"] if a["type"] == "request_review"]
        self.assertEqual([a["kind"] for a in requests], ["security_review"])
        self.assertNotIn(
            "PRRT_kwDORqU88s6xY_R9", [a.get("thread") for a in result["actions"]]
        )
        self.assertEqual(
            result["causes"], ["codex_finding_open: " + item["threads"][1]["url"]]
        )


class OwnerHoldTests(unittest.TestCase):
    def test_owner_holds_and_drafts_are_untouched(self):
        for change in (
            {"labels": ["do-not-merge"]},
            {"title": "x (do not merge)"},
            {"draft": True},
        ):
            with self.subTest(change=change):
                item = case(830)
                item["pr"].update(change)
                result = plan(item)
                self.assertEqual(
                    (result["actions"], result["skipped"]), ([], "owner_hold_or_draft")
                )

    def test_queue_treats_review_holds_as_work_not_as_owner_holds(self):
        for label in ("hold", "autopilot:hold"):
            self.assertFalse(held({"title": "t", "labels": [{"name": label}]}))
        self.assertTrue(held({"title": "t", "labels": [{"name": "do-not-merge"}]}))
        issue = {
            "authorized": True,
            "number": 3,
            "revision": "r",
            "snapshot": {},
            "title": "t",
            "labels": [{"name": "autopilot:hold"}],
        }
        self.assertEqual(len(candidates([], [issue])), 1)


if __name__ == "__main__":
    unittest.main()
