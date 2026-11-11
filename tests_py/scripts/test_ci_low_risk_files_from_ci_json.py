"""The resolver takes the low-risk file names from ci.json, so the workflow files
are the same in every repository (ADR-1131, amends ADR-1126)."""

import base64
import json
from pathlib import Path
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
REPO = "owner/any-repository"
# source: the heredoc openers of the resolver and of the ci.json validator in
# .github/workflows/pipeline-post-merge.yml and pipeline.yml.
RESOLVER = "          python3 - <<'PY'\n"
VALIDATOR = "          python3 - \"$GITHUB_WORKSPACE\" --github-output <<'PY'\n"
# source: .github/dependabot.yml of the fleet's repositories (uv, npm, cargo): the
# names Cortex's resolver held before ADR-1131 must no longer be in its source.
ECOSYSTEM_FILES = ("uv.lock", "pyproject.toml", "package.json", "Cargo.lock")


def embedded(workflow, opener):
    text = (WORKFLOWS / workflow).read_text()
    source = text.split(opener, 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(source)


def load(workflow, opener):
    namespace = {"__name__": "embedded_test"}
    exec(compile(embedded(workflow, opener), workflow, "exec"), namespace)
    return namespace


def commit():
    update = "- dependency-name: x\n  update-type: version-update:semver-patch\n"
    message = "deps: bump x\n\n" + update
    return {
        "author": {"login": "dependabot[bot]"},
        "committer": {"login": "web-flow"},
        "commit": {"message": message, "verification": {"verified": True}},
    }


class FakeApi:
    """document: what the default branch's ci.json parses to; files: the PR's."""

    def __init__(self, document, files=()):
        self.document, self.files, self.gets = document, files, []

    def records(self, path, key=None):
        if path.endswith("/commits"):
            return [commit()]
        return [{"filename": name} for name in self.files]

    def request(self, method, path, body=None):
        self.gets.append((method, path))
        content = base64.b64encode(json.dumps(self.document).encode()).decode()
        return {"type": "file", "encoding": "base64", "content": content}


class ResolverReadsCiJsonTests(unittest.TestCase):
    def setUp(self):
        self.ns = load("pipeline-post-merge.yml", RESOLVER)
        self.pr = {"number": 7, "user": {"login": "dependabot[bot]", "type": "Bot"}}

    def low(self, listed, files):
        api = FakeApi({"low_risk_files": listed}, files)
        return self.ns["_is_low_risk"](self.pr, REPO, api)

    def test_the_names_come_from_the_default_branch_ci_json(self):
        api = FakeApi({"low_risk_files": ["Cargo.lock"]})
        self.assertEqual(self.ns["_low_risk_files"](REPO, api), {"Cargo.lock"})
        # No `ref`: the contents API then reads the default branch.
        self.assertEqual(api.gets, [("GET", f"/repos/{REPO}/contents/ci.json")])

    def test_the_list_of_another_repository_decides(self):
        self.assertTrue(self.low(["Cargo.lock", "Cargo.toml"], ("Cargo.lock",)))
        self.assertFalse(self.low(["Cargo.lock", "Cargo.toml"], ("uv.lock",)))
        self.assertFalse(self.low([], ("uv.lock",)))

    def test_the_resolver_source_names_no_dependency_file(self):
        source = embedded("pipeline-post-merge.yml", RESOLVER)
        for name in ECOSYSTEM_FILES:
            self.assertNotIn(name, source)

    def test_a_missing_key_fails_the_resolver(self):
        for document in ({}, {"unit": "true"}, ["uv.lock"], None):
            with self.subTest(document=document):
                with self.assertRaises(self.ns["PostMergeError"]) as caught:
                    self.ns["_is_low_risk"](
                        self.pr, REPO, FakeApi(document, ("uv.lock",))
                    )
                self.assertIn("low_risk_files: missing", str(caught.exception))

    def test_a_missing_key_is_not_a_merge_that_waits(self):
        # ADR-1128: only a WAITING message ends green; this one must end red.
        self.assertFalse(
            "ci.json: low_risk_files: missing".startswith(self.ns["WAITING"])
        )

    def test_a_malformed_list_fails_the_resolver(self):
        for listed in ("uv.lock", [""], [7], ["a/uv.lock"], {"uv.lock": True}, None):
            with self.subTest(listed=listed):
                with self.assertRaises(self.ns["PostMergeError"]) as caught:
                    self.low(listed, ("uv.lock",))
                self.assertIn("must be a list of file names", str(caught.exception))

    def test_an_unreadable_ci_json_fails_the_resolver(self):
        api = FakeApi({})
        api.request = lambda *_: [{"name": "ci.json", "type": "dir"}]
        with self.assertRaises(self.ns["PostMergeError"]):
            self.ns["_low_risk_files"](REPO, api)
        api.request = lambda *_: {"encoding": "base64", "content": "bm90IGpzb24="}
        with self.assertRaises(self.ns["PostMergeError"]) as caught:
            self.ns["_low_risk_files"](REPO, api)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_a_file_is_matched_by_its_name_in_any_directory(self):
        listed = ["package.json", "pnpm-lock.yaml"]
        self.assertTrue(self.low(listed, ("packages/core/package.json",)))
        self.assertTrue(self.low(listed, ("pnpm-lock.yaml", "a/b/package.json")))
        self.assertFalse(self.low(listed, ("packages/core/package.json.bak",)))
        self.assertFalse(self.low(listed, ("package.json/index.js",)))

    def test_a_path_under_dot_github_is_never_low_risk(self):
        listed = ["package.json", "package-lock.json"]
        self.assertFalse(self.low(listed, (".github/claude-cli/package.json",)))
        self.assertFalse(
            self.low(listed, ("package.json", ".github/x/package-lock.json"))
        )
        self.assertTrue(self.low(listed, ("docs/.github/package.json",)))

    def test_a_person_s_pull_request_does_not_read_ci_json(self):
        api = FakeApi({})
        person = {"number": 7, "user": {"login": "someone", "type": "User"}}
        self.assertFalse(self.ns["_is_low_risk"](person, REPO, api))
        self.assertEqual(api.gets, [])


class ContractValidatesTheKeyTests(unittest.TestCase):
    def faults(self, *listed):
        """Faults of a valid ci.json whose low_risk_files is listed[0], or absent."""
        document = {key: "true" for key in self.ns["KEYS"]}
        document["version_file"] = "v.json"
        if listed:
            document["low_risk_files"] = listed[0]
        with tempfile.TemporaryDirectory() as root:
            Path(root, "v.json").write_text('{"version": "1.0.0"}')
            Path(root, "ci.json").write_text(json.dumps(document))
            return self.ns["faults"](Path(root))

    def setUp(self):
        self.ns = load("pipeline.yml", VALIDATOR)

    def test_a_list_of_file_names_is_valid_and_so_is_an_empty_one(self):
        self.assertEqual(self.faults(["uv.lock"]), [])
        self.assertEqual(self.faults([]), [])

    def test_a_missing_key_fails_the_contract(self):
        self.assertEqual(self.faults(), ["low_risk_files: missing"])

    def test_a_path_or_a_non_list_fails_the_contract(self):
        for value in ("uv.lock", ["sub/uv.lock"], [""], [1], None):
            with self.subTest(value=value):
                self.assertEqual(
                    self.faults(value),
                    ["low_risk_files: must be a list of file names"],
                )

    def test_both_workflows_embed_the_same_validator(self):
        self.assertEqual(
            embedded("pipeline.yml", VALIDATOR),
            embedded("pipeline-post-merge.yml", VALIDATOR),
        )

    def test_this_repository_s_ci_json_honours_the_contract(self):
        self.assertEqual(self.ns["faults"](ROOT), [])
        listed = json.loads((ROOT / "ci.json").read_text())["low_risk_files"]
        self.assertEqual(listed, ["uv.lock", "pyproject.toml"])


if __name__ == "__main__":
    unittest.main()
