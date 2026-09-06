"""CI Green must fail closed without importing application code or its DB."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import check_ci_gate_results as gate


def _event(fork: bool = False) -> dict:
    return {"pull_request": {"head": {"repo": {"fork": fork}}}}


def _needs(*changed: str) -> dict:
    needs = {job: {"result": "success", "outputs": {}} for job in gate.EXPECTED_JOBS}
    needs["changes"]["outputs"] = {
        name: "true" if name in changed else "false" for name in gate.FILTERS
    }
    return needs


def _skip(needs: dict, jobs: frozenset[str]) -> dict:
    for job in jobs:
        needs[job]["result"] = "skipped"
    return needs


class JustifiedSkips(unittest.TestCase):
    def test_docs_only_runs_only_changes_and_lint(self) -> None:
        needs = _skip(_needs("docs"), gate.CONDITIONAL_JOBS)
        self.assertEqual(gate.check(needs, "pull_request", _event()), [])

    def test_docker_only_requires_docker_jobs(self) -> None:
        needs = _skip(_needs("docker"), gate.CODE_JOBS)
        self.assertEqual(gate.check(needs, "pull_request", _event()), [])
        for job in gate.DOCKER_JOBS:
            with self.subTest(job=job):
                needs[job]["result"] = "skipped"
                self.assertTrue(gate.check(needs, "pull_request", _event()))
                needs[job]["result"] = "success"

    def test_code_deps_workflows_require_every_job(self) -> None:
        for changed in (("code",), ("docs", "code"), ("deps",), ("workflows",)):
            needs = _needs(*changed)
            self.assertEqual(gate.check(needs, "pull_request", _event()), [])
            for job in gate.CONDITIONAL_JOBS:
                with self.subTest(changed=changed, job=job):
                    needs[job]["result"] = "skipped"
                    self.assertTrue(gate.check(needs, "pull_request", _event()))
                    needs[job]["result"] = "success"

    def test_non_pr_runs_require_full_matrix_even_for_docs(self) -> None:
        for event_name in ("push", "workflow_dispatch"):
            needs = _needs("docs")
            self.assertEqual(gate.check(needs, event_name, {}), [])
            needs["test"]["result"] = "skipped"
            self.assertTrue(gate.check(needs, event_name, {}))

    def test_fork_guard_applies_only_to_vendor_cli_job(self) -> None:
        needs = _needs("code")
        needs["mcp-host-config"]["result"] = "skipped"
        self.assertEqual(gate.check(needs, "pull_request", _event(True)), [])
        self.assertTrue(gate.check(needs, "pull_request", _event(False)))
        needs["test"]["result"] = "skipped"
        self.assertTrue(gate.check(needs, "pull_request", _event(True)))


class FailClosed(unittest.TestCase):
    def test_failures_cancellation_and_invalid_results_never_pass(self) -> None:
        for result in ("failure", "cancelled", "pending", "", None):
            for job in gate.EXPECTED_JOBS:
                with self.subTest(result=result, job=job):
                    needs = _skip(_needs("docs"), gate.CONDITIONAL_JOBS)
                    needs[job]["result"] = result
                    self.assertTrue(gate.check(needs, "pull_request", _event()))

    def test_lint_failure_rejects_skipped_matrix(self) -> None:
        needs = _skip(_needs("code"), gate.CONDITIONAL_JOBS)
        needs["lint"]["result"] = "failure"
        failures = gate.check(needs, "pull_request", _event())
        self.assertTrue(any("lint=" in failure for failure in failures))

    def test_changes_and_lint_may_never_skip(self) -> None:
        for job in gate.ALWAYS_JOBS:
            needs = _skip(_needs("docs"), gate.CONDITIONAL_JOBS)
            needs[job]["result"] = "skipped"
            self.assertTrue(gate.check(needs, "pull_request", _event()))

    def test_missing_and_unexpected_jobs_fail(self) -> None:
        for job in gate.EXPECTED_JOBS:
            needs = _needs("docs")
            del needs[job]
            self.assertTrue(gate.check(needs, "pull_request", _event()))
        needs = _needs("docs")
        needs["unwatched"] = {"result": "success"}
        self.assertTrue(gate.check(needs, "pull_request", _event()))

    def test_missing_and_invalid_classifications_fail(self) -> None:
        for output in gate.FILTERS:
            for value in (True, False, "", "TRUE", None, [], {}):
                with self.subTest(output=output, value=value):
                    needs = _needs("docs")
                    needs["changes"]["outputs"][output] = value
                    self.assertTrue(gate.check(needs, "pull_request", _event()))
            needs = _needs("docs")
            del needs["changes"]["outputs"][output]
            self.assertTrue(gate.check(needs, "pull_request", _event()))

    def test_invalid_job_objects_and_output_objects_fail(self) -> None:
        for value in (None, [], "success"):
            needs = _needs("docs")
            needs["changes"] = value
            self.assertTrue(gate.check(needs, "pull_request", _event()))
            needs = _needs("docs")
            needs["changes"]["outputs"] = value
            self.assertTrue(gate.check(needs, "pull_request", _event()))

    def test_missing_or_invalid_fork_context_fails(self) -> None:
        for event in ({}, {"pull_request": None}, _event("false")):
            self.assertTrue(gate.check(_needs("docs"), "pull_request", event))

    def test_unsupported_event_context_fails(self) -> None:
        self.assertTrue(gate.check(_needs("docs"), "", {}))
        self.assertTrue(gate.check(_needs("docs"), "push", []))


class ExecutableContract(unittest.TestCase):
    def _run(self, needs: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            event_path.write_text(json.dumps(_event()), encoding="utf-8")
            env = {
                **os.environ,
                "NEEDS": needs,
                "GITHUB_EVENT_PATH": str(event_path),
                "GITHUB_EVENT_NAME": "pull_request",
                "ALLOWED_SKIPS": ",".join(sorted(gate.CONDITIONAL_JOBS)),
            }
            return subprocess.run(
                [sys.executable, str(Path(gate.__file__))],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_docs_only_cli_succeeds(self) -> None:
        result = self._run(json.dumps(_skip(_needs("docs"), gate.CONDITIONAL_JOBS)))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_json_cli_fails_with_diagnostic(self) -> None:
        result = self._run("{bad json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read CI gate inputs", result.stderr)


if __name__ == "__main__":
    unittest.main()
