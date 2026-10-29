"""Contract tests for this repository's actual generated merge controller.

Run: python3 -m unittest discover -s scripts/tests -p test_ci_workflow_authorization.py -v
Only stdlib is needed. IDs, SHAs and API records below are synthetic fixtures.
"""
import base64
from contextlib import redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import textwrap
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "fixture/reference"
HEAD = "a" * 40
MERGED = "b" * 40
WORKFLOW = ".github/workflows/pipeline.yml"


def load_resolver() -> ModuleType:
    """Compile the controller the consumer will run, including its embedded proof."""
    path = ROOT / ".github/workflows/pipeline-post-merge.yml"
    text = path.read_text(encoding="utf-8")
    _, found, step = text.partition("      - name: Resolve protected merge\n")
    if not found:
        raise ValueError("generated resolver step missing")
    _, found, remaining = step.partition("          python3 - <<'PY'\n")
    body, end, _ = remaining.partition("          PY\n")
    if not found or not end:
        raise ValueError("generated resolver heredoc missing")
    module = ModuleType("consumer_workflow_authorization_contract")
    module.__file__ = str(path)
    exec(compile(textwrap.dedent(body), str(path), "exec"), module.__dict__)
    return module


class FixtureGitHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        repo = {"full_name": REPOSITORY}
        self.run: dict[str, object] = {
            "id": 9, "node_id": "synthetic-run-node", "run_attempt": 1,
            "event": "pull_request", "status": "completed", "conclusion": "success",
            "head_repository": repo, "head_branch": "fixture/topic", "head_sha": HEAD,
            "name": "Pipeline", "path": WORKFLOW, "pull_requests": [{"number": 7}],
        }
        self.pr: dict[str, object] = {
            "number": 7, "state": "open", "draft": False, "merged": False,
            "title": "Synthetic contract fixture", "labels": [],
            "head": {"sha": HEAD, "repo": repo}, "base": {"ref": "main", "repo": repo},
        }
        self.file: dict[str, object] = {
            "path": WORKFLOW, "repositoryName": REPOSITORY,
            "repositoryFileUrl": f"https://github.com/{REPOSITORY}/blob/{HEAD}/{WORKFLOW}",
        }
        self.node: dict[str, object] = {"databaseId": 9, "runAttempt": 1, "file": self.file}
        self.graphql: dict[str, object] = {"data": {"node": self.node}}
        self.actual = (ROOT / WORKFLOW).read_bytes()
        self.installed = self.actual
        self.published = self.actual
        names = ["contract", "unit", "regression", "e2e", "review", "merge"] + [
            f"{kind} ({runner})" for kind in ("environment", "install")
            for runner in ("ubuntu-latest", "macos-latest", "windows-latest")
        ]
        self.jobs = [
            {"id": 100 + index, "name": name, "run_id": 9, "run_attempt": 1,
             "head_sha": HEAD, "status": "completed", "conclusion": "success"}
            for index, name in enumerate(names)
        ]

    def request(self, method: str, path: str, body: object = None) -> dict[str, object]:
        self.calls.append((method, path, body))
        if path.endswith("/actions/runs/9"):
            return self.run
        if path == "/graphql":
            if method != "POST" or body != {
                "query": load_resolver()._proof.RUN_FILE_QUERY,
                "variables": {"id": "synthetic-run-node"},
            }:
                raise AssertionError("executed workflow query lost its run binding")
            return self.graphql
        if "/contents/" in path:
            if method != "GET":
                raise AssertionError("definition reads must use the Contents API GET")
            if "cdeust/zetetic-team-subagents/" in path:
                content = self.published
            else:
                content = self.installed if path.endswith("ref=refs%2Fheads%2Fmain") else self.actual
            return {"type": "file", "encoding": "base64", "content": base64.b64encode(content).decode()}
        if path.endswith("/pulls/7/merge") and method == "PUT":
            if body != {"sha": HEAD, "merge_method": "squash"}:
                raise AssertionError("merge lost the tested-head precondition")
            self.pr.update(merged=True, merge_commit_sha=MERGED, state="closed")
            return {"merged": True, "sha": MERGED}
        if path.endswith("/pulls/7"):
            return self.pr
        if path.endswith("/compare/main..." + MERGED):
            return {"status": "identical", "merge_base_commit": {"sha": MERGED}}
        raise AssertionError("unexpected fixture API call")

    def records(self, path: str, key: str | None = None) -> list[dict[str, object]]:
        self.calls.append(("GET", path, key))
        if path.endswith("/actions/runs/9/jobs?filter=all") and key == "jobs":
            return self.jobs
        raise AssertionError("unexpected fixture API list")

    def merge_calls(self) -> list[tuple[str, str, object]]:
        return [call for call in self.calls if call[0] == "PUT"]


class WorkflowAuthorizationContract(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = load_resolver()
        self.api = FixtureGitHub()
        self.event = {"repository": {"full_name": REPOSITORY}, "workflow_run": dict(self.api.run)}

    def resolve(self) -> dict[str, str]:
        return self.resolver.resolve(self.event, REPOSITORY, self.api)

    def assert_blocked(self) -> None:
        with self.assertRaisesRegex(self.resolver.PostMergeError, "workflow proof"):
            self.resolve()
        self.assertEqual(self.api.merge_calls(), [])

    def assert_confirmed_merge(self) -> None:
        result = self.resolve()
        self.assertEqual(result["tested_sha"], MERGED)
        self.assertEqual(result["run_tests"], "true")
        self.assertEqual(result["pr_number"], "7")
        self.assertEqual(self.api.merge_calls(), [
            ("PUT", f"/repos/{REPOSITORY}/pulls/7/merge", {"sha": HEAD, "merge_method": "squash"}),
        ])

    def test_installed_definition_returns_confirmed_merge(self) -> None:
        self.api.published = b"different upstream definition"
        self.assert_confirmed_merge()
        upstream = any("/repos/cdeust/zetetic-team-subagents/" in call[1] for call in self.api.calls)
        self.assertFalse(upstream)

    def test_canonical_generated_upgrade_returns_confirmed_merge(self) -> None:
        self.api.installed = b"previous installed definition"
        self.assert_confirmed_merge()
        upstream = any("/repos/cdeust/zetetic-team-subagents/" in call[1] for call in self.api.calls)
        self.assertTrue(upstream)

    def test_successful_fake_job_names_do_not_authorize_merge(self) -> None:
        self.api.actual = b"fake workflow emitting every expected successful job name"
        self.assertTrue(all(job["conclusion"] == "success" for job in self.api.jobs))
        self.assert_blocked()

    def test_cross_repository_file_is_rejected(self) -> None:
        self.api.file["repositoryName"] = "fixture/other"
        self.assert_blocked()

    def test_different_run_attempt_is_rejected(self) -> None:
        self.api.node["runAttempt"] = 2
        self.assert_blocked()

    def test_different_run_identity_is_rejected(self) -> None:
        self.api.node["databaseId"] = 8
        self.assert_blocked()

    def test_graphql_errors_are_rejected(self) -> None:
        self.api.graphql = {"errors": [{"message": "synthetic denial"}]}
        self.assert_blocked()

    def test_missing_executed_file_is_rejected(self) -> None:
        self.api.node["file"] = None
        self.assert_blocked()

    def test_wrong_workflow_path_is_rejected(self) -> None:
        self.api.file["path"] = ".github/workflows/fake.yml"
        self.assert_blocked()

    def test_mutable_file_pointer_is_rejected(self) -> None:
        self.api.file["repositoryFileUrl"] = f"https://github.com/{REPOSITORY}/blob/main/{WORKFLOW}"
        self.assert_blocked()

    def test_pr_payload_cannot_replace_server_provenance(self) -> None:
        self.api.actual = b"fake workflow"
        self.event["workflow_run"] = {**self.api.run, "node_id": "forged-payload-node"}
        self.assert_blocked()

    def test_rejected_proof_has_nonzero_cli_and_no_output(self) -> None:
        self.api.actual = b"fake workflow"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event, output = root / "event.json", root / "outputs"
            event.write_text(json.dumps(self.event), encoding="utf-8")
            env = {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REPOSITORY": REPOSITORY,
                   "GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(output), "GH_TOKEN": "synthetic-fixture-token"}
            errors = StringIO()
            with patch.dict(os.environ, env), patch.object(self.resolver, "GitHub", return_value=self.api), redirect_stderr(errors):
                result = self.resolver.main()
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertIn("workflow proof", errors.getvalue())
            self.assertEqual(self.api.merge_calls(), [])


if __name__ == "__main__":
    unittest.main()
