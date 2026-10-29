"""Reject privileged review routes and missing post-merge gates.

Source: PR189 separated-events design, generated three-workflow contract.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

from tests_py.scripts.test_check_ci_gate_complete import change_job, gate


class PipelineRoutesTests(unittest.TestCase):
    def setUp(self):
        self.direct = gate.CI_WORKFLOW.read_text()
        self.engine = gate.POST_MERGE_WORKFLOW.read_text()
        self.caller = gate.CALLER_WORKFLOW.read_text()

    def routes(self, *, direct=None, engine=None, caller=None):
        return gate.check_routes(
            (
                self.direct if direct is None else direct,
                self.engine if engine is None else engine,
                self.caller if caller is None else caller,
            ),
            gate._job_bodies,
            gate._field,
        )

    def test_all_three_live_routes_and_engine_gates_pass(self):
        self.assertEqual(self.routes(), [])
        self.assertEqual(gate.check(self.engine, post_merge=True), [])
        self.assertEqual(gate.check_runtime_contract(self.engine, post_merge=True), [])

    def test_every_file_is_required_by_the_cli(self):
        for name in ("CI_WORKFLOW", "POST_MERGE_WORKFLOW", "CALLER_WORKFLOW"):
            with (
                self.subTest(name=name),
                patch.object(gate, name, Mock(exists=lambda: False)),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(gate.main(), 1)

    def test_caller_cannot_route_to_direct_or_remote_workflow(self):
        for target in (
            "./.github/workflows/pipeline.yml",
            "owner/repo/workflow.yml@main",
        ):
            with self.subTest(target=target):
                changed = self.caller.replace(
                    "./.github/workflows/pipeline-post-merge.yml", target
                )
                self.assertNotEqual(changed, self.caller)
                self.assertTrue(self.routes(caller=changed))

    def test_caller_cannot_inherit_all_secrets_or_gain_review_permissions(self):
        for before, after in (
            (
                "secrets:\n      RELEASE_TAG_SSH_KEY: "
                "${{ secrets.RELEASE_TAG_SSH_KEY }}",
                "secrets: inherit",
            ),
            ("actions: read", "actions: read\n      id-token: write"),
            ("contents: write", "contents: write\n      issues: write"),
            ("pull-requests: write", "pull-requests: read"),
            ("github.event.workflow_run.conclusion == 'success'", "true"),
            ("github.event.workflow_run.event == 'pull_request'", "true"),
            ("branches-ignore: [main]", "branches-ignore: [other]"),
            ("workflows: [Pipeline]", "workflows: [Other]"),
        ):
            with self.subTest(before=before):
                changed = self.caller.replace(before, after)
                self.assertNotEqual(changed, self.caller)
                self.assertTrue(self.routes(caller=changed))

    def test_engine_cannot_contain_review_or_merge_and_direct_has_no_resolver(self):
        for job in ("review", "merge"):
            with self.subTest(job=job):
                changed = self.engine + f"\n  {job}:\n    runs-on: ubuntu-latest\n"
                self.assertTrue(gate.check(changed, post_merge=True))
        self.assertTrue(gate.check(self.direct + "\n  resolve:\n    steps: []\n"))

    def test_engine_cannot_execute_claude_action_or_call_another_workflow(self):
        action = self.engine.replace(
            "uses: actions/checkout@", "uses: anthropics/claude-code-action@", 1
        )
        self.assertNotEqual(action, self.engine)
        self.assertTrue(self.routes(engine=action))
        nested = change_job(
            self.engine,
            "unit",
            lambda block: block.replace(
                "  unit:\n", "  unit:\n    uses: ./.github/workflows/pipeline.yml\n"
            ),
        )
        self.assertTrue(self.routes(engine=nested))

    def test_every_engine_gate_and_dependency_is_required(self):
        for job in gate.POST_MERGE_NEEDS:
            with self.subTest(job=job):
                changed = change_job(self.engine, job, lambda block: "")
                self.assertTrue(gate.check(changed, post_merge=True))
        changed = change_job(
            self.engine,
            "contract",
            lambda block: block.replace("needs: resolve", "needs: []"),
        )
        self.assertTrue(gate.check(changed, post_merge=True))

    def test_profiles_cannot_be_interchanged(self):
        self.assertTrue(gate.check(self.direct, post_merge=True))
        self.assertTrue(gate.check(self.engine))

    def test_resolver_requires_exact_direct_receipt_and_job_results(self):
        for before, after in (
            ('run.get("path") == ".github/workflows/pipeline.yml"', "True"),
            ('run.get("name") == "Pipeline"', "True"),
            ('"regression", "e2e", "merge"', '"regression", "e2e"'),
            ('"ubuntu-latest", "macos-latest", "windows-latest"', '"ubuntu-latest"'),
            ("len(actual) == len(expected) and set(actual) == expected", "True"),
            ("len(matching) == 1,", "True,"),
            ('allowed = job.get("conclusion") == "success"', "allowed = True"),
            ('job.get("status") == "completed" and allowed,', "True,"),
            ("_validate_run(source, repository)", "pass"),
            ("_validate_run(run, repository)", "pass"),
            (
                "              _validate_jobs(jobs)\n              return run",
                "              return run",
            ),
        ):
            with self.subTest(before=before):
                changed = change_job(
                    self.engine,
                    "resolve",
                    lambda block, before=before, after=after: block.replace(
                        before, after
                    ),
                )
                self.assertTrue(gate.check_runtime_contract(changed, post_merge=True))
