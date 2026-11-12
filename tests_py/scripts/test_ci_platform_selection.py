"""A pull request that only changes documentation runs environment and install on
Linux alone, and the resolver accepts that matrix only when it finds the same
thing from the default branch's ci.json (ADR-1133)."""

import base64
import http.client
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
REPO = "owner/any-repository"
# source: the heredoc openers of the embedded scripts in pipeline.yml and
# pipeline-post-merge.yml.
RESOLVER = "          python3 - <<'PY'\n"
SELECTOR = "          python3 - \"$GITHUB_WORKSPACE\" --platforms <<'PY'\n"
# source: the matrix of the environment and install jobs before ADR-1133.
ALL = ["ubuntu-latest", "macos-latest", "windows-latest"]
LINUX = ALL[:1]
DOCS = ["docs/", "wiki/", "CHANGELOG.md"]
# source: GitHub REST, "List pull requests files": 100 a page, 3000 in all.
PAGE, LISTED_AT_MOST = 100, 3000
RENAMES = [
    {"filename": f"docs/b{index}.md", "previous_filename": f"docs/a{index}.md"}
    for index in range(LISTED_AT_MOST // 2)
]


def embedded(workflow, opener):
    text = (WORKFLOWS / workflow).read_text()
    source = text.split(opener, 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(source)


def load(workflow, opener):
    namespace = {"__name__": "embedded_test"}
    exec(compile(embedded(workflow, opener), workflow, "exec"), namespace)
    return namespace


def function_source(source, name):
    start = source.index(f"def {name}(")
    return source[start : source.index("\n\n\n", start)]


def rows(*names):
    return [name if isinstance(name, dict) else {"filename": name} for name in names]


def fetcher(listed):
    return lambda page: listed[(page - 1) * PAGE : page * PAGE]


class FakeApi:
    """document: what the default branch's ci.json parses to; files: the PR's."""

    def __init__(self, document, files=()):
        self.document, self.files, self.gets = document, files, []

    def records(self, path, key=None):
        return rows(*self.files)

    def request(self, method, path, body=None):
        self.gets.append((method, path))
        content = base64.b64encode(json.dumps(self.document).encode()).decode()
        return {"type": "file", "encoding": "base64", "content": content}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.ns = load("pipeline.yml", SELECTOR)

    def systems(self, *names, event="pull_request", docs=DOCS):
        return self.ns["select"](event, docs, fetcher(rows(*names)))[0]

    def test_a_documentation_only_pull_request_runs_linux_alone(self):
        self.assertEqual(
            self.systems("docs/a.md", "wiki/x/y.md", "CHANGELOG.md"), LINUX
        )

    def test_any_path_outside_the_list_keeps_the_three_systems(self):
        for names in (
            ("docs/a.md", "mcp_server/core/x.py"),
            ("docsx/a.md",),
            ("x/CHANGELOG.md",),
            ("CHANGELOG.md.bak",),
            ("ci.json",),
            (".github/workflows/pipeline.yml",),
            ("docs/what?.md",),
            ("docs/NUL.md",),
            ("docs/a.md ",),
            ("docs/a\nb.md",),
        ):
            with self.subTest(names=names):
                self.assertEqual(self.systems(*names), ALL)

    def test_a_rename_counts_under_both_of_its_names(self):
        moved = {"filename": "docs/a.md", "previous_filename": "mcp_server/a.py"}
        self.assertEqual(self.systems(moved), ALL)
        inside = {"filename": "docs/b.md", "previous_filename": "docs/a.md"}
        self.assertEqual(self.systems(inside), LINUX)

    def test_another_event_or_an_empty_list_keeps_the_three_systems(self):
        def never(page):
            raise AssertionError("the file list must not be read")

        self.assertEqual(self.ns["select"]("push", DOCS, never)[0], ALL)
        self.assertEqual(self.ns["select"]("pull_request", [], never)[0], ALL)
        self.assertEqual(self.systems(), ALL)

    def test_an_unreadable_file_list_keeps_the_three_systems(self):
        cut = http.client.IncompleteRead(b"")
        for error in (OSError("refused"), ValueError("not json"), cut):
            with self.subTest(error=error):

                def broken(page, error=error):
                    raise error

                self.assertEqual(
                    self.ns["select"]("pull_request", DOCS, broken)[0], ALL
                )
        for row in ({"status": "added"}, {"filename": 7}, {"filename": ""}):
            with self.subTest(row=row):
                listed = fetcher([row])
                self.assertEqual(
                    self.ns["select"]("pull_request", DOCS, listed)[0], ALL
                )

    def test_a_list_at_github_s_limit_keeps_the_three_systems(self):
        full = [f"docs/{index}.md" for index in range(LISTED_AT_MOST)]
        self.assertEqual(self.systems(*full), ALL)
        self.assertEqual(self.systems(*full[:-1]), LINUX)
        # Paths are counted, as the resolver counts them: a rename is two.
        self.assertEqual(self.systems(*RENAMES), ALL)

    def test_the_reason_never_quotes_a_path(self):
        # A file name can hold a line break followed by a workflow command.
        evil = "src/x\n::add-mask::y"
        reason = self.ns["select"]("pull_request", DOCS, fetcher(rows(evil)))[1]
        self.assertNotIn("add-mask", reason)

    def test_the_step_exports_the_matrix_as_json(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "ci.json").write_text(json.dumps({"docs_paths": DOCS}))
            output = Path(root, "out")
            env = {"EVENT_NAME": "push", "GITHUB_OUTPUT": str(output)}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(self.ns["main"]([root]), 0)
            self.assertEqual(output.read_text(), f"platforms={json.dumps(ALL)}\n")


def jobs(environment, install, conclusion="success"):
    names = ["contract", "unit", "regression", "e2e", "merge"]
    names += [f"environment ({runner})" for runner in environment]
    names += [f"install ({runner})" for runner in install]
    return [
        {"name": name, "status": "completed", "conclusion": conclusion}
        for name in names
    ]


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.ns = load("pipeline-post-merge.yml", RESOLVER)
        self.pr = {"number": 7, "merged": False}

    def only_docs(self, document, *files):
        return self.ns["_documentation_only"](self.pr, REPO, FakeApi(document, files))

    def test_the_three_systems_are_not_a_reduced_matrix(self):
        self.assertIs(self.ns["_validate_jobs"](jobs(ALL, ALL)), False)

    def test_linux_alone_on_both_jobs_is_a_reduced_matrix(self):
        self.assertIs(self.ns["_validate_jobs"](jobs(LINUX, LINUX)), True)

    def test_any_other_matrix_is_refused(self):
        two, mac = ALL[:2], ALL[1:2]
        for environment, install in (
            (two, two), (mac, mac), ([], []), (LINUX, ALL), (ALL, LINUX),
        ):  # fmt: skip
            with self.subTest(environment=environment, install=install):
                with self.assertRaises(self.ns["PostMergeError"]):
                    self.ns["_validate_jobs"](jobs(environment, install))

    def test_the_linux_leg_of_a_reduced_matrix_must_have_succeeded(self):
        with self.assertRaises(self.ns["PostMergeError"]):
            self.ns["_validate_jobs"](jobs(LINUX, LINUX, conclusion="failure"))

    def test_the_paths_come_from_the_default_branch_ci_json(self):
        api = FakeApi({"docs_paths": DOCS}, ("docs/a.md",))
        self.assertTrue(self.ns["_documentation_only"](self.pr, REPO, api))
        # No `ref`: the contents API then reads the default branch.
        self.assertEqual(api.gets, [("GET", f"/repos/{REPO}/contents/ci.json")])

    def test_a_code_change_or_a_missing_key_is_not_documentation_only(self):
        self.assertFalse(self.only_docs({"docs_paths": DOCS}, "docs/a.md", "ci.json"))
        self.assertFalse(self.only_docs({"docs_paths": DOCS}))
        self.assertFalse(self.only_docs({}, "docs/a.md"))
        moved = {"filename": "docs/a.md", "previous_filename": "scripts/a.py"}
        for row in (moved, "docs/what?.md", {"status": "added"}, {"filename": 7}):
            with self.subTest(row=row):
                self.assertFalse(self.only_docs({"docs_paths": DOCS}, row))

    def test_a_file_list_at_github_s_limit_is_not_documentation_only(self):
        full = [f"docs/{index}.md" for index in range(LISTED_AT_MOST)]
        self.assertFalse(self.only_docs({"docs_paths": DOCS}, *full))
        self.assertTrue(self.only_docs({"docs_paths": DOCS}, *full[:-1]))
        self.assertFalse(self.only_docs({"docs_paths": DOCS}, *RENAMES))

    def test_a_malformed_list_fails_the_resolver(self):
        for listed in (
            "docs/",
            [".github/"],
            ["/x/"],
            ["a/../b/"],
            ["ci.json"],
            [""],
            [7],
        ):
            with self.subTest(listed=listed):
                with self.assertRaises(self.ns["PostMergeError"]) as caught:
                    self.only_docs({"docs_paths": listed}, "docs/a.md")
                self.assertIn("must be a list of paths", str(caught.exception))

    def resolve(self, reduced, documentation):
        """resolve() with its GitHub reads replaced; merged records a merge."""
        merged = []
        self.ns.update(
            _source_run=lambda *_: {"head_sha": "a" * 40, "reduced_matrix": reduced},
            _pull_request=lambda *_: (7, self.pr),
            _documentation_only=lambda *_: documentation,
            _merge_open_pr=lambda *_: merged.append(True) or "b" * 40,
            _confirm_pr_merge=lambda *_: None,
        )
        return self.ns["resolve"]({}, REPO, None), merged

    def test_a_reduced_matrix_merges_only_a_documentation_only_pull_request(self):
        result, merged = self.resolve(reduced=True, documentation=True)
        self.assertEqual((result["run_tests"], merged), ("true", [True]))
        with self.assertRaises(self.ns["PostMergeError"]) as caught:
            self.resolve(reduced=True, documentation=False)
        self.assertIn("requires the three systems", str(caught.exception))
        # ADR-1128: only a WAITING message ends green; this refusal ends red.
        self.assertFalse(str(caught.exception).startswith(self.ns["WAITING"]))

    def test_the_three_systems_never_ask_whether_the_change_is_documentation(self):
        result, merged = self.resolve(reduced=False, documentation=None)
        self.assertEqual((result["run_tests"], merged), ("true", [True]))


class WorkflowTests(unittest.TestCase):
    def test_both_scripts_hold_the_same_documentation_only(self):
        self.assertEqual(
            function_source(embedded("pipeline.yml", SELECTOR), "documentation_only"),
            function_source(
                embedded("pipeline-post-merge.yml", RESOLVER), "documentation_only"
            ),
        )

    def test_the_two_jobs_take_their_matrix_from_the_selection(self):
        text = (WORKFLOWS / "pipeline.yml").read_text()
        matrix = "os: ${{ fromJSON(needs.contract.outputs.platforms) }}"
        self.assertEqual(text.count(matrix), 2)
        self.assertIn("platforms: ${{ steps.platforms.outputs.platforms }}", text)
        self.assertNotIn("os: [", text)

    def test_the_pipeline_after_merge_keeps_the_three_systems(self):
        text = (WORKFLOWS / "pipeline-post-merge.yml").read_text()
        self.assertEqual(text.count(f"os: [{', '.join(ALL)}]"), 2)
        self.assertNotIn("fromJSON(needs.contract.outputs.platforms)", text)


if __name__ == "__main__":
    unittest.main()
