"""Adversarial run-bound claude[bot] review evidence: one invariant per test.

Protocol (ADR-1116): the review job of .github/workflows/claude.yml publishes
each native review on commit_id=<head> with first body line
<!-- claude-review:v2 kind=code|security findings=N run=<run id> -->; the run
must be a claude.yml workflow_run on main whose job "review <head>" validated
that kind. The job lookup is injected here as a dict.
"""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci_claude_reviews.py"
SHA = "a" * 40  # GitHub SHA-1 field, synthetic fixture.
OTHER = "b" * 40
BOT = {"login": "claude[bot]", "type": "Bot"}
# source: synthetic fixture id of the producing claude.yml run, not GitHub data
RUN = 900


def module():
    spec = importlib.util.spec_from_file_location("ci_claude_reviews", SCRIPT)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def review(kind="code", findings=0, review_id=1, **extra):
    """claude[bot] v2 marker review on SHA citing RUN; extra overrides fields."""
    run = extra.pop("run", RUN)
    value = {
        "id": review_id,
        "user": copy.deepcopy(BOT),
        "commit_id": SHA,
        "state": "COMMENTED",
        "body": f"<!-- claude-review:v2 kind={kind} findings={findings} run={run} -->"
        "\n## Review",
    }
    value.update(copy.deepcopy(extra))
    return value


def clean():
    return [review("code", 0, 1), review("security", 0, 2)]


def producer(status="completed", **conclusions):
    """The 'review <head>' job of the producing run, with validation steps."""
    steps = [
        {"name": f"Validate {kind} review execution", "conclusion": result}
        for kind, result in {
            "code": "success",
            "security": "success",
            **conclusions,
        }.items()
    ]
    return {"name": f"review {SHA}", "status": status, "steps": steps}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.reader = module()
        self.jobs = {RUN: producer()}

    def evidence(self, rows, sha=SHA):
        return self.reader.review_evidence(rows, sha, self.jobs.get)

    def outcome(self, rows):
        result = self.evidence(rows)
        return result["state"], result["reason"]

    def test_both_validated_clean_reviews_on_exact_head_succeed(self):
        result = self.evidence(clean())
        self.assertEqual(
            (result["state"], result["reason"]), ("success", "reviews_complete")
        )
        self.assertTrue(result["reviews_complete"])
        self.assertEqual((result["code"]["review_id"], result["code"]["run"]), (1, RUN))

    def test_absent_review_is_pending_never_failed(self):
        self.assertEqual(self.outcome([]), ("pending", "review_missing"))
        self.assertEqual(self.outcome([review("code")]), ("pending", "review_pending"))

    def test_review_on_stale_sha_is_pending(self):
        rows = [review("code", commit_id=OTHER), review("security", commit_id=OTHER)]
        self.assertEqual(self.outcome(rows), ("pending", "review_missing"))

    def test_marker_review_by_another_identity_is_ignored(self):
        for user in (
            {"login": "github-actions[bot]", "type": "Bot"},
            {"login": "claude[bot]", "type": "User"},
            {"login": "cdeust", "type": "User"},
            None,
        ):
            with self.subTest(user=user):
                rows = [review("code", user=user), review("security", user=user)]
                self.assertEqual(self.outcome(rows), ("pending", "review_missing"))

    def test_unbound_marker_from_tag_or_manual_post_is_not_evidence(self):
        # An @claude session posts as claude[bot] too: without a producing
        # claude.yml run that validated this kind, its marker is ignored.
        legacy = "<!-- claude-review:v1 kind={} findings=0 -->"
        tagged = [review("code", body=legacy.format("code"))]
        tagged.append(review("security", 0, 2, body=legacy.format("security")))
        for rows in (
            tagged,
            [review("code", run=901), review("security", 0, 2, run=901)],
            [review("code", body="<!-- claude-review:v2 kind=code findings=0 -->")],
        ):
            with self.subTest(rows=rows):
                self.assertEqual(self.outcome(rows), ("pending", "review_missing"))

    def test_failed_or_skipped_execution_validation_fails_the_kind(self):
        for job in (producer(code="failure"), producer(code="skipped")):
            self.jobs[RUN] = job
            self.assertEqual(self.outcome(clean()), ("blocked", "review_failed"))
        self.jobs[RUN] = dict(producer(), steps=[])
        self.assertEqual(self.outcome(clean()), ("blocked", "review_failed"))

    def test_running_producer_keeps_the_kind_pending(self):
        self.jobs[RUN] = producer(status="in_progress")
        self.assertEqual(self.outcome(clean()), ("pending", "review_pending"))

    def test_findings_block_until_a_new_head(self):
        result = self.evidence([review("code", 2, 1), review("security", 0, 2)])
        self.assertEqual(
            (result["state"], result["reason"]), ("blocked", "review_unresolved")
        )
        self.assertTrue(result["reviews_complete"])
        self.assertEqual(result["code"]["findings"], 2)

    def test_malformed_bound_marker_fails(self):
        for first in (
            "<!-- claude-review:v2 kind=other findings=0 run=900 -->",
            "<!-- claude-review:v2 kind=code findings=abc run=900 -->",
            "<!-- claude-review:v2 kind=code findings=01 run=900 -->",
            "<!-- claude-review:v3 kind=code findings=0 run=900 -->",
        ):
            with self.subTest(first=first):
                rows = clean() + [review(review_id=3, body=first + "\nbody")]
                self.assertEqual(self.outcome(rows), ("blocked", "review_failed"))

    def test_duplicate_kind_on_one_head_fails_instead_of_latest_wins(self):
        rows = [review("code", 3, 1), review("code", 0, 4), review("security", 0, 2)]
        result = self.evidence(rows)
        self.assertEqual(
            (result["state"], result["reason"]), ("blocked", "review_failed")
        )
        self.assertEqual(result["code"]["state"], "failed")

    def test_non_comment_review_state_fails(self):
        for state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            with self.subTest(state=state):
                rows = [review("code", state=state), review("security", 0, 2)]
                self.assertEqual(self.outcome(rows)[1], "review_failed")

    def test_unrelated_reviews_and_comments_are_ignored(self):
        rows = clean() + [
            review(review_id=7, body="LGTM"),
            review(review_id=8, body=None),
            review(review_id=9, user={"login": "cdeust", "type": "User"}, body="ok"),
        ]
        self.assertEqual(self.outcome(rows)[0], "success")

    def test_malformed_api_rows_block_with_protocol(self):
        for mutate in (
            lambda row: row.update(id=0),
            lambda row: row.update(id=True),
            lambda row: row.update(commit_id="short"),
            lambda row: row.update(body=5),
            lambda row: row.update(state=None),
            lambda row: row.update(user="claude[bot]"),
        ):
            rows = clean()
            mutate(rows[0])
            self.assertEqual(self.outcome(rows), ("blocked", "protocol"))
        self.assertEqual(self.evidence("rows")["reason"], "protocol")
        self.assertEqual(self.evidence(clean(), sha="nope")["reason"], "arguments")


class ProvenanceTests(unittest.TestCase):
    """attest(): the producing job is read from the Actions API, never the body."""

    def setUp(self):
        self.reader = module()
        self.run = {
            "id": RUN,
            "path": ".github/workflows/claude.yml",
            "event": "workflow_run",
            "head_branch": "main",
            "repository": {"full_name": "cdeust/Cortex"},
        }
        self.jobs = [{"total_count": 2, "jobs": [producer(), {"name": "verify"}]}]

    def api(self, endpoint, paginate=False, missing=False):
        if endpoint.endswith(f"/actions/runs/{RUN}"):
            return copy.deepcopy(self.run) if self.run else None
        if endpoint.endswith(f"/actions/runs/{RUN}/jobs") and paginate:
            return copy.deepcopy(self.jobs)
        raise AssertionError(endpoint)

    def job(self):
        return self.reader.attest("cdeust/Cortex", SHA, self.api)(RUN)

    def test_genuine_claude_workflow_run_yields_the_head_review_job(self):
        self.assertEqual(self.job()["name"], f"review {SHA}")

    def test_other_workflow_event_branch_repo_or_missing_run_is_unbound(self):
        for field, value in (
            ("path", ".github/workflows/pipeline.yml"),
            ("event", "issue_comment"),
            ("head_branch", "fix/claude-bot-review"),
            ("repository", {"full_name": "fork/Cortex"}),
            ("id", 901),
        ):
            with self.subTest(field=field):
                self.setUp()
                self.run[field] = value
                self.assertIsNone(self.job())
        self.setUp()
        self.run = None
        self.assertIsNone(self.job())

    def test_job_for_another_head_is_unbound(self):
        self.jobs[0]["jobs"][0]["name"] = f"review {OTHER}"
        self.assertIsNone(self.job())


if __name__ == "__main__":
    unittest.main()
