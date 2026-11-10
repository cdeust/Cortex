"""The Claude review budget: three reviews per PR, counted from run metadata.

Source: ADR-1119 and scripts/ci_review_budget.py. The workflow wiring tests pin
the names the script and claude-review.yml must agree on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import unittest.mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_review_budget as budget  # noqa: E402

REVIEW = ROOT / ".github/workflows/claude-review.yml"
SHA = "a" * 40


def run(run_id, day, sha=SHA, conclusion="success", prs=(7,)):
    return {
        "id": run_id,
        "conclusion": conclusion,
        "head_sha": sha,
        "created_at": f"2026-11-0{day}T10:00:00Z",
        "prs": list(prs),
    }


def fake_gh(runs, jobs):
    """Return what `gh api ... --jq` would print for the two endpoints."""

    def gh(args):
        if args[0].endswith("/runs") and "claude-review.yml" in args[0]:
            return "\n".join(json.dumps(r) for r in runs)
        run_id = int(args[0].split("/")[-2])
        return json.dumps(jobs[run_id])

    return gh


class DecideTests(unittest.TestCase):
    def test_first_review_runs_with_no_previous_commit(self):
        out = budget.decide([], [])
        self.assertEqual(
            out, {"round": 1, "cap": 3, "skip": "false", "reviewed_sha": ""}
        )

    def test_third_review_still_runs_and_names_the_latest_reviewed_commit(self):
        newer, older = "b" * 40, "c" * 40
        out = budget.decide([run(2, 3, newer), run(1, 1, older)], [])
        self.assertEqual((out["round"], out["skip"]), (3, "false"))
        self.assertEqual(out["reviewed_sha"], newer)

    def test_fourth_review_is_skipped(self):
        out = budget.decide([run(1, 1), run(2, 2), run(3, 3)], [])
        self.assertEqual((out["round"], out["skip"]), (4, "true"))

    def test_label_grants_exactly_one_more_review(self):
        label = [budget.BYPASS_LABEL]
        three = [run(i, i) for i in (1, 2, 3)]
        self.assertEqual(budget.decide(three, label)["skip"], "false")
        four = [*three, run(4, 4)]
        out = budget.decide(four, label)
        self.assertEqual((out["round"], out["skip"]), (5, "true"))

    def test_a_malformed_commit_is_a_protocol_error(self):
        with self.assertRaises(budget.BudgetError):
            budget.decide([run(1, 1, "not-a-sha\nskip=false")], [])


class CountTests(unittest.TestCase):
    def count(self, runs, jobs):
        return budget.budget(fake_gh(runs, jobs), "o/r", 7, 99, "feat", [])

    def test_only_successful_runs_of_this_pr_that_ran_the_action_count(self):
        runs = [
            run(1, 1),
            run(2, 2),  # cap run: success, but the action step was skipped
            run(3, 3, conclusion="failure"),
            run(4, 4, prs=(8,)),
            run(99, 5),  # the current run
        ]
        jobs = {1: ["success"], 2: ["skipped"], 3: ["success"], 4: ["success"]}
        out = self.count(runs, jobs)
        self.assertEqual((out["round"], out["reviewed_sha"]), (2, SHA))

    def test_skipped_runs_do_not_move_the_reviewed_commit(self):
        reviewed, skipped = "b" * 40, "c" * 40
        runs = [run(1, 1, reviewed), run(2, 2, skipped)]
        out = self.count(runs, {1: ["success"], 2: ["skipped"]})
        self.assertEqual(out["reviewed_sha"], reviewed)

    def test_api_failure_is_not_swallowed(self):
        def boom(args):
            raise subprocess.CalledProcessError(1, "gh")

        with self.assertRaises(subprocess.CalledProcessError):
            budget.budget(boom, "o/r", 7, 99, "feat", [])


@unittest.skipUnless(shutil.which("jq"), "jq is not installed")
class JqFilterTests(unittest.TestCase):
    def jq(self, expr, payload):
        done = subprocess.run(
            ["jq", "-c", expr],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return done.stdout

    def test_run_filter_keeps_id_conclusion_sha_and_pr_numbers(self):
        calls = []
        budget.candidate_runs(lambda a: calls.append(a) or "", "o/r", 7, 99, "feat")
        expr = calls[0][calls[0].index("--jq") + 1]
        raw = {"workflow_runs": [{**run(1, 1), "pull_requests": [{"number": 7}]}]}
        row = json.loads(self.jq(expr, raw))
        self.assertEqual(row["prs"], [7])
        self.assertEqual(row["head_sha"], SHA)

    def test_job_filter_selects_the_action_step_only(self):
        calls = []
        record = lambda a: calls.append(a) or "[]"  # noqa: E731
        budget.ran_the_action(record, "o/r", {"id": 1})
        expr = calls[0][calls[0].index("--jq") + 1]
        steps = [
            {"name": "Checkout repository", "conclusion": "success"},
            {"name": budget.ACTION_STEP, "conclusion": "skipped"},
        ]
        gate = {"name": budget.BUDGET_JOB, "steps": []}
        review = {"name": "Claude review", "steps": steps}
        got = json.loads(self.jq(expr, {"jobs": [gate, review]}))
        self.assertEqual(got, ["skipped"])

    def test_a_review_of_the_workflow_before_the_contract_does_not_count(self):
        # ADR-1129: no budget job in the run, so it posted no verdict the merge
        # could read. ai-architect-mcp-spec #182, 2026-11-10: such reviews used
        # the whole budget and the pull request could never be merged.
        calls = []
        record = lambda a: calls.append(a) or "[]"  # noqa: E731
        budget.ran_the_action(record, "o/r", {"id": 1})
        expr = calls[0][calls[0].index("--jq") + 1]
        done = [{"name": budget.ACTION_STEP, "conclusion": "success"}]
        old = {"jobs": [{"name": "Claude review", "steps": done}]}
        self.assertEqual(json.loads(self.jq(expr, old)), [])
        new = {"jobs": [{"name": budget.BUDGET_JOB, "steps": []}, *old["jobs"]]}
        self.assertEqual(json.loads(self.jq(expr, new)), ["success"])

    def test_the_budget_job_name_is_the_workflow_s(self):
        workflow = yaml.safe_load(REVIEW.read_text())
        self.assertEqual(workflow["jobs"]["budget"]["name"], budget.BUDGET_JOB)


class CliTests(unittest.TestCase):
    def invoke(self, runs, jobs, labels="[]"):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out"
            env = {
                "GH_REPO": "o/r",
                "PR": "7",
                "RUN_ID": "99",
                "HEAD_REF": "feat",
                "LABELS": labels,
                "GITHUB_OUTPUT": str(out_file),
            }
            gh = fake_gh(runs, jobs)
            stdout = StringIO()
            with (
                unittest.mock.patch.dict(os.environ, env),
                unittest.mock.patch.object(budget, "gh_api", gh),
                redirect_stdout(stdout),
            ):
                self.assertEqual(budget.main(), 0)
            return out_file.read_text().splitlines(), stdout.getvalue()

    def test_outputs_are_plain_key_value_lines(self):
        lines, text = self.invoke([run(1, 1)], {1: ["success"]})
        self.assertEqual(
            lines, ["round=2", "cap=3", "skip=false", f"reviewed_sha={SHA}"]
        )
        self.assertIn("review 2 of 3", text)

    def test_exhausted_budget_says_what_to_do_instead_of_commenting(self):
        runs = [run(i, i) for i in (1, 2, 3)]
        lines, text = self.invoke(runs, {i: ["success"] for i in (1, 2, 3)})
        self.assertIn("skip=true", lines)
        self.assertIn("refinement PR", text)
        self.assertIn(budget.BYPASS_LABEL, text)


class WorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(REVIEW.read_text())
        self.jobs = self.workflow["jobs"]

    def action(self):
        return next(
            step
            for step in self.jobs["review"]["steps"]
            if step.get("uses", "").startswith("anthropics/claude-code-action@")
        )

    def test_reviews_of_one_pr_are_admitted_one_at_a_time(self):
        self.assertEqual(
            self.workflow["concurrency"],
            {
                "group": "claude-review-${{ github.event.pull_request.number }}",
                "cancel-in-progress": False,
            },
        )

    def test_the_counted_step_name_is_the_action_step(self):
        self.assertEqual(self.action()["name"], budget.ACTION_STEP)

    def test_budget_job_has_read_only_scopes_and_no_secret(self):
        job = self.jobs["budget"]
        self.assertEqual(job["permissions"], {"contents": "read", "actions": "read"})
        self.assertNotIn("secrets.", yaml.safe_dump(job))
        self.assertEqual(
            job["steps"][-1]["run"], "python3 -I scripts/ci_review_budget.py"
        )

    def test_budget_checks_out_main_and_keeps_no_credentials(self):
        checkout = self.jobs["budget"]["steps"][0]
        self.assertEqual(checkout["with"]["ref"], "main")
        self.assertFalse(checkout["with"]["persist-credentials"])

    def test_review_waits_for_the_budget_and_honours_its_skip(self):
        review = self.jobs["review"]
        self.assertEqual(review["needs"], "budget")
        self.assertIn("needs.budget.outputs.skip != 'true'", review["if"])

    def test_budget_and_review_share_the_same_event_predicate(self):
        base = [
            "head.repo.full_name == github.repository",
            "!github.event.pull_request.draft",
            "github.actor != 'dependabot[bot]'",
        ]
        for clause in base:
            self.assertIn(clause, self.jobs["budget"]["if"])
            self.assertIn(clause, self.jobs["review"]["if"])

    def test_prompt_carries_the_severity_contract_from_the_budget_outputs(self):
        prompt = self.action()["with"]["prompt"]
        self.assertTrue(prompt.startswith("/review-pr "))
        for needle in (
            "needs.budget.outputs.round",
            "needs.budget.outputs.cap",
            "needs.budget.outputs.reviewed_sha",
            "A Blocker is a defect you traced or reproduced",
            "at most 3 Notes",
            "which part of the PR is accepted",
            'End with exactly one line: "Verdict: approve" or "Verdict: block".',
        ):
            self.assertIn(needle, prompt)

    def test_cap_is_three(self):
        self.assertEqual(budget.CAP, 3)


if __name__ == "__main__":
    unittest.main()
