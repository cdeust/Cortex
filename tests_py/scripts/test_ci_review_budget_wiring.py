"""How claude-review.yml wires the budget script into the review it admits.

Source: ADR-1119 (the cap), ADR-1130 (the run link), ADR-1147 (a rebased head).
The names here are the ones scripts/ci_review_budget.py and the workflow share.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_review_budget as budget  # noqa: E402

REVIEW = ROOT / ".github/workflows/claude-review.yml"


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
        self.assertEqual(
            job["permissions"],
            {"contents": "read", "actions": "read", "pull-requests": "read"},
        )
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

    def test_the_budget_job_hands_the_rewritten_history_to_the_review(self):
        # A rebase onto main removes the reviewed commit from the PR's history:
        # "only the commits pushed after it" then names commits that do not exist.
        outputs = self.jobs["budget"]["outputs"]
        self.assertEqual(outputs["rewritten"], "${{ steps.count.outputs.rewritten }}")
        prompt = self.action()["with"]["prompt"]
        rewritten = '"${{ needs.budget.outputs.rewritten }}"'
        incremental = "review only the commits pushed after it"
        full = "review the full diff of the PR (gh pr diff), not only new commits"
        resolved = "how each conflict with main was resolved"
        for needle in (rewritten, incremental, full, resolved):
            self.assertIn(needle, prompt)
        self.assertIn('("true" above is the only value that says it has)', prompt)
        self.assertLess(prompt.index(rewritten), prompt.index(incremental))
        self.assertLess(prompt.index(incremental), prompt.index(full))

    def test_prompt_puts_the_run_link_in_every_comment_that_carries_the_verdict(self):
        # ADR-1130: the resolver binds a verdict to a head through the run its comment
        # links. A review posted with `gh pr comment` carried the verdict and no link.
        prompt = self.action()["with"]["prompt"]
        link = (
            '"[View job run](${{ github.server_url }}/${{ github.repository }}'
            '/actions/runs/${{ github.run_id }})"'
        )
        self.assertIn(link, prompt)
        self.assertIn("in every comment that carries the verdict line", prompt)
        self.assertLess(prompt.index("End with exactly one line"), prompt.index(link))


if __name__ == "__main__":
    unittest.main()
