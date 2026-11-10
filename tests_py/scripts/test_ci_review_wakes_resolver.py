"""The review's completion wakes the resolver too, so the merge does not depend on
which of the review and the Pipeline finishes first (ADR-1127)."""

from pathlib import Path
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
REPO = "cdeust/Cortex"
HEAD = "a" * 40


def resolver():
    text = (WORKFLOWS / "pipeline-post-merge.yml").read_text()
    source = text.split("          python3 - <<'PY'\n", 1)[1].split(
        "\n          PY", 1
    )[0]
    namespace = {"__name__": "resolver_test"}
    exec(compile(textwrap.dedent(source), "trusted_resolver", "exec"), namespace)
    return namespace


def review(**changes):
    run = {
        "name": "PR Review",
        "path": ".github/workflows/claude-review.yml",
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_repository": {"full_name": REPO},
        "head_sha": HEAD,
    }
    return {**run, **changes}


class FakeApi:
    def __init__(self, pipelines):
        self.pipelines, self.paths = pipelines, []

    def records(self, path, key=None):
        self.paths.append(path)
        return self.pipelines


class ReviewWakesResolverTests(unittest.TestCase):
    def pipeline_of(self, source, pipelines):
        api = FakeApi(pipelines)
        return resolver()["_pipeline_of_review"](source, REPO, api), api

    def held(self, source, pipelines, message):
        ns = resolver()
        with self.assertRaises(ns["PostMergeError"]) as caught:
            ns["_pipeline_of_review"](source, REPO, FakeApi(pipelines))
        self.assertIn(message, str(caught.exception))

    def test_the_newest_successful_pipeline_of_the_head_is_the_source(self):
        runs = [{"id": 5, "head_sha": HEAD}, {"id": 9, "head_sha": HEAD}]
        found, api = self.pipeline_of(review(), runs)
        self.assertEqual(found["id"], 9)
        self.assertEqual(
            api.paths,
            [
                f"/repos/{REPO}/actions/workflows/pipeline.yml/runs"
                f"?head_sha={HEAD}&event=pull_request&status=success"
            ],
        )

    def test_a_pipeline_of_another_head_does_not_count(self):
        self.held(review(), [{"id": 9, "head_sha": "b" * 40}], "has not succeeded")

    def test_no_successful_pipeline_holds_the_merge(self):
        self.held(review(), [], "Pipeline has not succeeded on this head")

    def test_a_review_that_failed_or_ran_elsewhere_is_refused(self):
        for change in (
            {"conclusion": "failure"},
            {"status": "in_progress"},
            {"event": "pull_request_target"},
            {"path": ".github/workflows/other.yml"},
        ):
            self.held(review(**change), [], "did not complete successfully")
        fork = review(head_repository={"full_name": "someone/Cortex"})
        self.held(fork, [], "head repository differs")

    def test_a_pr_merged_before_the_review_ended_is_not_tested_twice(self):
        text = (WORKFLOWS / "pipeline-post-merge.yml").read_text()
        body = text.split("def resolve(event", 1)[1].split("def main", 1)[0]
        held = body.split('run.get("woken_by_review")', 1)[1].split("return {", 2)[1]
        self.assertIn('"run_tests": "false"', held)
        self.assertLess(
            body.index('run.get("woken_by_review")'),
            body.index('"run_tests": "true"'),
        )

    def test_both_workflows_wake_the_resolver(self):
        caller = (WORKFLOWS / "pipeline-after-merge.yml").read_text()
        self.assertIn("workflows: [Pipeline, PR Review]", caller)
        review_name = (WORKFLOWS / "claude-review.yml").read_text().splitlines()[0]
        self.assertEqual(review_name, "name: PR Review")


if __name__ == "__main__":
    unittest.main()
