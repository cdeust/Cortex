"""A Dependabot minor or patch update of the dependency files merges without a
review; every other change keeps the reviewed path (ADR-1126)."""

import base64
import json
from pathlib import Path
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
REPO = "cdeust/Cortex"
HEAD = "a" * 40
MINOR = "version-update:semver-minor"
PATCH = "version-update:semver-patch"
MAJOR = "version-update:semver-major"
# source: ci.json at the repository root, `low_risk_files` (ADR-1131).
LISTED = json.loads((ROOT / "ci.json").read_text())["low_risk_files"]


def resolver():
    text = (ROOT / ".github/workflows/pipeline-post-merge.yml").read_text()
    source = text.split("          python3 - <<'PY'\n", 1)[1].split(
        "\n          PY", 1
    )[0]
    namespace = {"__name__": "resolver_test"}
    exec(compile(textwrap.dedent(source), "trusted_resolver", "exec"), namespace)
    return namespace


def commit(
    updates=(PATCH,), author="dependabot[bot]", verified=True, committer="web-flow"
):
    lines = "".join(f"- dependency-name: x\n  update-type: {u}\n" for u in updates)
    return {
        "author": {"login": author},
        "committer": {"login": committer},
        "commit": {
            "message": f"deps: bump x\n\n---\nupdated-dependencies:\n{lines}...\n",
            "verification": {"verified": verified},
        },
    }


def pull(login="dependabot[bot]", kind="Bot"):
    return {
        "number": 7,
        "state": "open",
        "draft": False,
        "title": "deps: bump x",
        "labels": [],
        "user": {"login": login, "type": kind},
    }


class FakeApi:
    def __init__(self, commits, files):
        self.commits, self.files, self.puts = commits, files, []

    def records(self, path, key=None):
        if path.endswith("/commits"):
            return self.commits
        if path.endswith("/files"):
            return [
                name if isinstance(name, dict) else {"filename": name}
                for name in self.files
            ]
        return []  # no review run, no comment: the reviewed path holds

    def request(self, method, path, body=None):
        if (method, path) == ("GET", f"/repos/{REPO}/contents/ci.json"):
            content = json.dumps({"low_risk_files": LISTED}).encode()
            return {"encoding": "base64", "content": base64.b64encode(content).decode()}
        self.puts.append((method, path, body))
        return {"merged": True, "sha": "c" * 40}


class LowRiskTierTests(unittest.TestCase):
    def low(self, commits=None, files=("uv.lock",), pr=None):
        api = FakeApi([commit()] if commits is None else commits, files)
        return resolver()["_is_low_risk"](pr or pull(), REPO, api)

    def test_a_dependabot_patch_of_the_lock_is_low_risk(self):
        self.assertTrue(self.low())

    def test_a_grouped_minor_and_patch_update_is_low_risk(self):
        self.assertTrue(self.low([commit((MINOR, PATCH, PATCH))]))
        self.assertTrue(self.low(files=("uv.lock", "pyproject.toml")))

    def test_a_major_update_is_not(self):
        self.assertFalse(self.low([commit((MAJOR,))]))
        self.assertFalse(self.low([commit((PATCH, MAJOR))]))

    def test_an_update_type_it_does_not_know_is_not(self):
        self.assertFalse(self.low([commit(("version-update:semver-minorx",))]))
        self.assertFalse(self.low([commit(())]))
        self.assertFalse(self.low([]))

    def test_a_workflow_or_any_other_file_is_not(self):
        self.assertFalse(self.low(files=(".github/workflows/scorecard.yml",)))
        self.assertFalse(self.low(files=("uv.lock", "mcp_server/server.py")))
        self.assertFalse(self.low(files=()))

    def test_another_author_or_an_unsigned_commit_is_not(self):
        self.assertFalse(self.low(pr=pull(login="cdeust", kind="User")))
        self.assertFalse(self.low(pr=pull(kind="User")))
        self.assertFalse(self.low([commit(author="cdeust")]))
        self.assertFalse(self.low([commit(verified=False)]))

    def test_a_bot_attributed_commit_signed_by_a_person_is_not(self):
        # Dependabot's e-mail as author, a contributor's own verified key.
        self.assertFalse(self.low([commit(committer="cdeust")]))
        self.assertFalse(self.low([commit(committer=None)]))

    def test_a_second_commit_on_the_branch_is_not(self):
        self.assertFalse(self.low([commit(), commit()]))

    def test_a_dependency_without_its_update_type_is_not(self):
        untyped = commit()
        untyped["commit"]["message"] += "- dependency-name: y\n"
        self.assertFalse(self.low([untyped]))

    def test_a_file_renamed_to_a_dependency_file_is_not(self):
        renamed = {
            "filename": "uv.lock",
            "previous_filename": ".github/workflows/pipeline.yml",
        }
        self.assertFalse(self.low(files=(renamed,)))

    def test_a_low_risk_pr_merges_without_a_review(self):
        api = FakeApi([commit()], ("uv.lock",))
        merge = resolver()["_merge_open_pr"]
        self.assertEqual(merge(pull(), "/merge", HEAD, api, REPO), "c" * 40)
        self.assertEqual(
            api.puts, [("PUT", "/merge", {"sha": HEAD, "merge_method": "squash"})]
        )

    def test_any_other_pr_still_needs_the_review(self):
        ns = resolver()
        for api in (
            FakeApi([commit((MAJOR,))], ("uv.lock",)),
            FakeApi([commit()], (".github/workflows/pipeline.yml",)),
        ):
            with self.assertRaises(ns["PostMergeError"]) as caught:
                ns["_merge_open_pr"](pull(), "/merge", HEAD, api, REPO)
            self.assertIn("no Claude review ran", str(caught.exception))
            self.assertEqual(api.puts, [])

    def test_a_hold_label_still_holds_a_low_risk_pr(self):
        ns = resolver()
        pr = {**pull(), "labels": [{"name": "hold"}]}
        api = FakeApi([commit()], ("uv.lock",))
        with self.assertRaises(ns["PostMergeError"]):
            ns["_merge_open_pr"](pr, "/merge", HEAD, api, REPO)
        self.assertEqual(api.puts, [])


if __name__ == "__main__":
    unittest.main()
