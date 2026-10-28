"""All authors require completed reviews at both protected merge boundaries."""

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


def completed_jobs():
    # Source: the canonical five test categories and three-OS matrices.
    names = ["contract", "unit", "regression", "e2e", "review", "merge"]
    names += [
        f"{kind} ({os})"
        for kind in ("environment", "install")
        for os in ("ubuntu-latest", "macos-latest", "windows-latest")
    ]
    return [
        {"name": name, "status": "completed", "conclusion": "success"} for name in names
    ]


class RequiredReviewTests(unittest.TestCase):
    def test_resolver_rejects_skipped_review_for_every_actor(self):
        namespace = resolver()
        jobs = completed_jobs()
        next(job for job in jobs if job["name"] == "review")["conclusion"] = "skipped"
        for actor in ("dependabot[bot]", "claude[bot]", "cdeust"):
            with (
                self.subTest(actor=actor),
                self.assertRaises(namespace["PostMergeError"]),
            ):
                namespace["_validate_jobs"](jobs, actor)

    def test_resolver_accepts_fully_completed_review_for_all_actors(self):
        namespace = resolver()
        for actor in ("dependabot[bot]", "claude[bot]", "cdeust"):
            with self.subTest(actor=actor):
                namespace["_validate_jobs"](completed_jobs(), actor)


if __name__ == "__main__":
    unittest.main()
