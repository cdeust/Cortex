"""Failure paths, merge-run selection, receipts and pagination (#834 reviews)."""

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_autopilot_converge as cli  # noqa: E402
import ci_autopilot_converge_observe as observer  # noqa: E402
from ci_autopilot_converge_plan import ELIGIBILITY_STEP, plan  # noqa: E402
from tests_py.scripts.test_ci_autopilot_converge import converged  # noqa: E402

HEAD = "e5117943a3d394f7028abc3b70d6573eb3f10948"  # PR 830 head before fe32c7d0.
PIPE = {"path": ".github/workflows/pipeline.yml", "head_sha": HEAD}
SECURITY = (
    "<!-- codex-review-receipt:v1 -->\n\n### 🛡️ Codex Security Review\n\n{verdict}"
    "\n\n**Reviewed commit:** `e5117943a3`"
)
QUIET = {"pr": 5, "head": HEAD, "actions": [], "causes": []}
CLEAN = "Security review completed. No security issues were found in this pull request."


def row(name, conclusion, run, job):
    url = f"https://github.com/o/r/actions/runs/{run}/job/{job}"
    return {"name": name, "conclusion": conclusion, "detailsUrl": url}


def receipt(identity, updated, verdict=CLEAN, login=observer.BOT):
    kind = "Bot" if login.endswith("[bot]") else "User"
    body = SECURITY.format(verdict=verdict)
    user = {"login": login, "type": kind}
    url = f"u{identity}"
    return {
        "id": identity,
        "updated_at": updated,
        "user": user,
        "body": body,
        "html_url": url,
    }


def answers(table):
    observer._run_meta.cache_clear()
    return patch.object(observer, "run_gh", side_effect=lambda *a: table[a[-1]])


class MergeRunTests(unittest.TestCase):
    def test_newest_pipeline_run_of_the_head_decides(self):
        rollup = [row("merge", "FAILURE", 5, 50), row("merge", "SUCCESS", 6, 60)]
        table = {"repos/o/r/actions/runs/5": PIPE, "repos/o/r/actions/runs/6": PIPE}
        with answers(table):
            self.assertIsNone(observer._merge_job("o/r", rollup, HEAD))

    def test_wrong_row_then_right_row(self):
        rollup = [row("merge", "FAILURE", 7, 70), row("merge", "FAILURE", 8, 80)]
        steps = [{"name": ELIGIBILITY_STEP, "conclusion": "failure"}]
        table = {
            "repos/o/r/actions/runs/7": {**PIPE, "path": ".github/workflows/x.yml"},
            "repos/o/r/actions/runs/8": PIPE,
            "repos/o/r/actions/jobs/80": {"run_id": 8, "steps": steps},
        }
        with answers(table):
            job = observer._merge_job("o/r", rollup, HEAD)
        # A plain failed merge job reruns itself.
        self.assertEqual((job["job_id"], job["rerun_job"]), (80, 80))

    def test_no_pipeline_row_and_foreign_job_id_read_as_none(self):
        rollup = [row("merge", "FAILURE", 9, 90)]
        foreign = {"run_id": 1, "steps": []}
        for table in (
            {"repos/o/r/actions/runs/9": {**PIPE, "head_sha": "f" * 40}},
            {"repos/o/r/actions/runs/9": PIPE, "repos/o/r/actions/jobs/90": foreign},
        ):
            with self.subTest(table=sorted(table)), answers(table):
                self.assertIsNone(observer._merge_job("o/r", rollup, HEAD))

    def test_pending_merge_without_its_own_review_job_is_named(self):
        rollup = [
            row("merge pending review", "FAILURE", 4, 40),
            row("review", "SUCCESS", 3, 30),  # another run: never used
        ]
        steps = [{"name": ELIGIBILITY_STEP, "conclusion": "failure"}]
        table = {
            "repos/o/r/actions/runs/4": PIPE,
            "repos/o/r/actions/runs/3": PIPE,
            "repos/o/r/actions/jobs/40": {"run_id": 4, "steps": steps},
        }
        with answers(table):
            job = observer._merge_job("o/r", rollup, HEAD)
        self.assertIsNone(job["rerun_job"])
        item = converged(830)
        item["merge"] = job
        cause = "merge_pending_review_without_review_job: run 4"
        self.assertEqual(plan(item)["causes"], [cause])

    def test_partial_lift_is_retried_from_the_failed_step(self):
        item = converged(830)
        item["pr"]["labels"] = []  # label already removed by an earlier pass
        merge = {"run_id": 1, "job_id": 77, "rerun_job": 76}
        item["merge"] = {**merge, "failed_step": ELIGIBILITY_STEP}
        self.assertEqual(plan(item)["actions"], [{"type": "rerun_job", "job": 76}])


class ReceiptTests(unittest.TestCase):
    def test_only_the_latest_bot_receipt_for_the_head_counts(self):
        older = receipt(1, "2026-10-29T08:00:00Z")
        newer = receipt(2, "2026-10-29T09:00:00Z", verdict="Found 1 issue.")
        self.assertIsNone(observer._security_receipt([older, newer], HEAD))
        self.assertEqual(observer._security_receipt([older], HEAD), "u1")

    def test_a_receipt_from_a_user_is_ignored(self):
        forged = receipt(3, "2026-10-29T08:00:00Z", login="someone")
        self.assertIsNone(observer._security_receipt([forged], HEAD))

    def test_receipt_never_concludes_merge_and_never_serves_code_review(self):
        item = converged(830)
        item["summary"]["security_review"]["has_any_findings"] = None
        item["summary"]["security_review"]["has_unresolved_findings"] = None
        item["summary"]["code_review"]["has_any_findings"] = None
        item["summary"]["code_review"]["has_unresolved_findings"] = None
        item["security_receipt"] = "u1"
        result = plan(item)
        kinds = [a["kind"] for a in result["actions"] if a["type"] == "request_review"]
        self.assertEqual(kinds, ["code_review"])
        gap = "codex_security_flags_null_after_clean_receipt: u1"
        self.assertIn(gap, result["causes"])


class FailurePathTests(unittest.TestCase):
    def args(self):
        return SimpleNamespace(repo="o/r", apply=True)

    def pull(self, **change):
        pull = {"number": 5, "headRefOid": HEAD, "isDraft": False, "labels": []}
        return {**pull, "title": "t", **change}

    def test_observe_failure_is_published_red_on_the_head(self):
        error = subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 502 Bad Gateway")
        with (
            patch.object(cli, "observe_pull", side_effect=error),
            patch.object(cli, "_published_now", return_value=None),
            patch.object(cli, "gh", return_value=None) as gh,
        ):
            result = cli._guarded(self.args(), self.pull(), None)
        cause = "observe_failed: CalledProcessError HTTP 502 Bad Gateway"
        self.assertEqual(result["causes"], [cause])
        self.assertIn("state=failure", gh.call_args_list[0].args)

    def test_plan_and_apply_failures_are_named_by_stage(self):
        obs = {"published": {"state": "failure", "description": "x"}}
        for stage, patches in (
            ("plan_failed", {"plan": AttributeError("a")}),
            ("apply_failed", {"apply": LookupError("b")}),
        ):
            with self.subTest(stage=stage):
                plan_effect = patches.get("plan") or (lambda _o: dict(QUIET))
                with (
                    patch.object(cli, "observe_pull", return_value=obs),
                    patch.object(cli, "plan", side_effect=plan_effect),
                    patch.object(cli, "apply", side_effect=patches.get("apply")),
                    patch.object(cli, "gh", return_value=None),
                ):
                    result = cli._guarded(self.args(), self.pull(), None)
                self.assertTrue(result["causes"][0].startswith(stage))

    def test_owner_held_or_draft_failure_posts_nothing(self):
        for change in ({"isDraft": True}, {"labels": [{"name": "do-not-merge"}]}):
            with (
                self.subTest(change=change),
                patch.object(cli, "observe_pull", side_effect=KeyError("k")),
                patch.object(cli, "gh", return_value=None) as gh,
            ):
                result = cli._guarded(self.args(), self.pull(**change), None)
            self.assertEqual(result["skipped"], "owner_hold_or_draft")
            self.assertEqual(gh.call_args_list, [])

    def test_a_failed_status_post_is_swallowed_after_logging(self):
        error = subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 422")
        with (
            patch.object(cli, "observe_pull", side_effect=KeyError("k")),
            patch.object(cli, "_published_now", return_value=None),
            patch.object(cli, "gh", side_effect=error),
        ):
            result = cli._guarded(self.args(), self.pull(), None)
        self.assertTrue(result["causes"][0].startswith("observe_failed"))


class PaginationTests(unittest.TestCase):
    def test_requests_and_published_read_every_combined_status_page(self):
        context = "autopilot-converge/request-security_review"
        pages = [
            {"statuses": [{"context": context, "created_at": "t1"}]},
            {
                "statuses": [
                    {
                        "context": "autopilot-converge",
                        "state": "success",
                        "description": "d",
                    }
                ]
            },
        ]
        pull = {
            "number": 5,
            "headRefOid": HEAD,
            "title": "t",
            "isDraft": False,
            "labels": [],
            "statusCheckRollup": [],
        }

        def fake(*args, **_kw):
            endpoint = args[-1]
            if endpoint.endswith("/status?per_page=100"):
                return pages
            if endpoint.startswith("query=") or args[1] == "graphql":
                return []
            return [[]]

        with patch.object(observer, "run_gh", side_effect=fake):
            with patch.object(observer, "review_threads", return_value=[]):
                obs = observer.observe_pull("o/r", pull)
        self.assertEqual(obs["requests"][0]["kind"], "security_review")
        self.assertEqual(obs["published"], {"state": "success", "description": "d"})


if __name__ == "__main__":
    unittest.main()
