"""The review job is not a required job at the protected merge boundary (owner rule 2026-10-29)."""

from pathlib import Path
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]


def resolver():
    text = (ROOT / ".github/workflows/pipeline-post-merge.yml").read_text()
    source = text.split("          python3 - <<'PY'\n", 1)[1].split(
        "\n          PY", 1
    )[0]
    namespace = {"__name__": "resolver_test"}
    exec(compile(textwrap.dedent(source), "trusted_resolver", "exec"), namespace)
    return namespace


def completed_jobs(*extra):
    # Source: the canonical test categories, their aggregate merge and the three-OS matrices.
    names = ["contract", "unit", "regression", "e2e", "merge", *extra]
    names += [
        f"{kind} ({os})"
        for kind in ("environment", "install")
        for os in ("ubuntu-latest", "macos-latest", "windows-latest")
    ]
    return [
        {"name": name, "status": "completed", "conclusion": "success"} for name in names
    ]


class ReviewIsNotRequiredTests(unittest.TestCase):
    def test_resolver_accepts_tests_and_merge_without_any_review_job(self):
        namespace = resolver()
        namespace["_validate_jobs"](completed_jobs())

    def test_resolver_ignores_the_review_job_in_every_state(self):
        namespace = resolver()
        for conclusion in ("failure", "cancelled", "skipped", None):
            for status in ("completed", "in_progress", "queued"):
                with self.subTest(status=status, conclusion=conclusion):
                    jobs = completed_jobs("review")
                    review = next(job for job in jobs if job["name"] == "review")
                    review.update(status=status, conclusion=conclusion)
                    namespace["_validate_jobs"](jobs)

    def test_a_red_test_job_still_blocks_with_a_green_review(self):
        namespace = resolver()
        for name in ("contract", "unit", "regression", "e2e", "merge", "install (macos-latest)"):
            with self.subTest(name=name), self.assertRaises(namespace["PostMergeError"]):
                jobs = completed_jobs("review")
                next(job for job in jobs if job["name"] == name)["conclusion"] = "failure"
                namespace["_validate_jobs"](jobs)

    def test_the_resolver_source_names_no_review_job(self):
        text = (ROOT / ".github/workflows/pipeline-post-merge.yml").read_text()
        source = text.split("          python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
        for forbidden in ('"review"', "merge pending review", "review_pending"):
            self.assertNotIn(forbidden, source)

    def test_the_review_job_cannot_fail_the_pipeline(self):
        text = (ROOT / ".github/workflows/pipeline.yml").read_text()
        block = text.split("\n  review:\n", 1)[1].split("\n  merge:\n", 1)[0]
        self.assertIn("    continue-on-error: true\n", block.split("    steps:", 1)[0])
        merge = text.split("\n  merge:\n", 1)[1].split("\n  tag:\n", 1)[0]
        needs = next(l for l in merge.splitlines() if l.startswith("    needs:"))
        self.assertNotIn("review", needs)


if __name__ == "__main__":
    unittest.main()
