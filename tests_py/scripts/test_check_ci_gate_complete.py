"""Mutation checks for the generated Pipeline dependency and result gates."""

from __future__ import annotations

import importlib.util
import io
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_spec = importlib.util.spec_from_file_location(
    "scripts.check_ci_gate_complete", _SCRIPTS / "check_ci_gate_complete.py"
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def change_job(text: str, job: str, transform) -> str:
    pattern = rf"(?ms)^  {re.escape(job)}:\n.*?(?=^  [A-Za-z0-9_-]+:|\Z)"
    changed, count = re.subn(pattern, lambda match: transform(match.group()), text)
    if count != 1 or changed == text:
        raise AssertionError(f"mutation did not change exactly one {job} block")
    return changed


class PipelineGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = gate.CI_WORKFLOW.read_text(encoding="utf-8")

    def failures(self, workflow: str) -> list[str]:
        return gate.check(workflow) + gate.check_runtime_contract(workflow)

    def test_live_generated_pipeline_passes(self) -> None:
        self.assertEqual(gate.CI_WORKFLOW.name, "pipeline.yml")
        self.assertEqual(self.failures(self.workflow), [])

    def test_each_required_job_must_exist(self) -> None:
        for job in gate.EXPECTED_NEEDS:
            with self.subTest(job=job):
                changed = change_job(self.workflow, job, lambda block: "")
                self.assertTrue(any(f"'{job}'" in f for f in gate.check(changed)))

    def test_new_job_cannot_run_outside_gates(self) -> None:
        changed = self.workflow + "\n  orphan:\n    runs-on: ubuntu-latest\n"
        self.assertTrue(any("orphan" in f for f in gate.check(changed)))

    def test_each_prerequisite_is_required(self) -> None:
        for job, prerequisites in gate.EXPECTED_NEEDS.items():
            for removed in prerequisites:
                with self.subTest(job=job, prerequisite=removed):
                    remaining = [p for p in prerequisites if p != removed]
                    replacement = f"    needs: [{', '.join(remaining)}]"
                    changed = change_job(
                        self.workflow,
                        job,
                        lambda block, replacement=replacement: re.sub(
                            r"(?m)^    needs:.*$", replacement, block
                        ),
                    )
                    self.assertTrue(gate.check(changed))

    def test_unknown_duplicate_and_self_dependencies_fail(self) -> None:
        for dependency in ("ghost", "contract", "unit"):
            with self.subTest(dependency=dependency):
                changed = change_job(
                    self.workflow,
                    "unit",
                    lambda block, dependency=dependency: block.replace(
                        "needs: contract", f"needs: [contract, {dependency}]"
                    ),
                )
                self.assertTrue(gate.check(changed))

    def test_contract_cannot_wait_for_a_test(self) -> None:
        changed = change_job(
            self.workflow,
            "contract",
            lambda block: block.replace(
                "  contract:\n", "  contract:\n    needs: unit\n"
            ),
        )
        self.assertTrue(gate.check(changed))

    def test_tests_and_contract_cannot_be_skipped(self) -> None:
        for job in gate.REQUIRED_RESULTS:
            with self.subTest(job=job):
                changed = change_job(
                    self.workflow,
                    job,
                    lambda block, job=job: block.replace(
                        f"  {job}:\n", f"  {job}:\n    if: false\n"
                    ),
                )
                self.assertTrue(gate.check_runtime_contract(changed))

    def test_tests_and_contract_cannot_ignore_failures(self) -> None:
        for job in gate.REQUIRED_RESULTS:
            with self.subTest(job=job):
                changed = change_job(
                    self.workflow,
                    job,
                    lambda block, job=job: block.replace(
                        f"  {job}:\n", f"  {job}:\n    continue-on-error: true\n"
                    ),
                )
                self.assertTrue(gate.check_runtime_contract(changed))

    def test_merge_result_guard_cannot_be_skipped(self) -> None:
        changed = self.workflow.replace(
            "      - name: Require completed tests and review\n",
            "      - name: Require completed tests and review\n        if: false\n",
        )
        self.assertNotEqual(changed, self.workflow)
        self.assertTrue(gate.check_runtime_contract(changed))

    def test_merge_result_guard_cannot_ignore_failure(self) -> None:
        changed = self.workflow.replace(
            "      - name: Require completed tests and review\n",
            "      - name: Require completed tests and review\n"
            "        continue-on-error: true\n",
        )
        self.assertNotEqual(changed, self.workflow)
        self.assertTrue(gate.check_runtime_contract(changed))

    def test_merge_and_review_keep_failure_path_and_pr_scope(self) -> None:
        for job in ("merge", "review"):
            for fragment in (
                "always() && ",
                "!cancelled() && ",
                "&& !github.event.pull_request.draft",
                "&& github.event.pull_request.head.repo.full_name == github.repository",
            ):
                with self.subTest(job=job, fragment=fragment):
                    changed = change_job(
                        self.workflow,
                        job,
                        lambda block, fragment=fragment: block.replace(fragment, "", 1),
                    )
                    self.assertTrue(gate.check_runtime_contract(changed))

    def test_tag_cannot_ignore_failed_prerequisites(self) -> None:
        changed = change_job(
            self.workflow,
            "tag",
            lambda block: block.replace("!cancelled()", "always()", 1),
        )
        self.assertTrue(gate.check_runtime_contract(changed))

    def test_tag_cannot_run_on_pull_requests(self) -> None:
        changed = change_job(
            self.workflow,
            "tag",
            lambda block: block.replace("== 'push'", "== 'pull_request'"),
        )
        self.assertTrue(gate.check_runtime_contract(changed))

    def test_merge_requires_each_actual_result_binding(self) -> None:
        for job in (*gate.REQUIRED_RESULTS, "review"):
            with self.subTest(job=job):
                changed = change_job(
                    self.workflow,
                    "merge",
                    lambda block, job=job: block.replace(
                        f"needs.{job}.result", "needs.ghost.result"
                    ),
                )
                self.assertTrue(gate.check_runtime_contract(changed))

    def test_merge_rejects_expanded_test_success_policy(self) -> None:
        for result in ("skipped", "cancelled", "timed_out", "failure"):
            with self.subTest(result=result):
                changed = change_job(
                    self.workflow,
                    "merge",
                    lambda block, result=result: block.replace(
                        "*=success) ;;", f"*=success|*={result}) ;;"
                    ),
                )
                self.assertTrue(gate.check_runtime_contract(changed))

    def test_review_skip_exception_cannot_be_reintroduced(self) -> None:
        changed = change_job(
            self.workflow,
            "merge",
            lambda block: block.replace(
                "success:*) ;;", "success:*|'skipped:dependabot[bot]') ;;"
            ),
        )
        self.assertTrue(gate.check_runtime_contract(changed))

    def test_merge_guard_cannot_drop_a_result_or_error_exit(self) -> None:
        for old, new in (
            ('"e2e=$E2E" ', ""),
            ("exit 1", "exit 0"),
            ("blocked=1", "blocked="),
        ):
            with self.subTest(old=old):
                changed = change_job(
                    self.workflow,
                    "merge",
                    lambda block, old=old, new=new: block.replace(old, new),
                )
                self.assertTrue(gate.check_runtime_contract(changed))

    def test_duplicate_yaml_job_or_field_fails(self) -> None:
        duplicate = self.workflow + "\n  unit:\n    needs: contract\n"
        self.assertTrue(gate.check(duplicate))
        changed = change_job(
            self.workflow,
            "unit",
            lambda block: block.replace(
                "needs: contract", "needs: contract\n    needs: contract"
            ),
        )
        self.assertTrue(gate.check(changed))

    def test_main_reports_success(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(gate.main(), 0)
        self.assertIn("Pipeline gate completeness: OK", output.getvalue())

    def test_main_reports_missing_file_and_bad_gate(self) -> None:
        for workflow in (
            Mock(exists=lambda: False),
            Mock(exists=lambda: True, read_text=lambda **kwargs: "jobs:\n"),
        ):
            with self.subTest(workflow=workflow):
                with (
                    patch.object(gate, "CI_WORKFLOW", workflow),
                    redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(gate.main(), 1)


class WorkflowParserTests(unittest.TestCase):
    def test_needs_scalar_inline_and_block_forms(self) -> None:
        for body, expected in (
            (["    needs: contract"], ["contract"]),
            (["    needs: [contract, unit]"], ["contract", "unit"]),
            (
                ["    needs:", "      - contract", "      # comment", "      - unit"],
                ["contract", "unit"],
            ),
        ):
            with self.subTest(body=body):
                self.assertEqual(gate._parse_needs(body), expected)

    def test_step_conditions_do_not_make_job_conditional(self) -> None:
        body = ["    steps:", "      - name: test", "        if: false"]
        self.assertEqual(gate._field(body, "if"), "")

    def test_folded_conditions_are_read_fully(self) -> None:
        self.assertEqual(
            gate._field(
                ["    if: >-", "      always()", "      && !cancelled()", "    steps:"],
                "if",
            ),
            "always() && !cancelled()",
        )

    def test_parser_stops_at_next_top_level_key(self) -> None:
        bodies = gate._job_bodies(
            "name: sample\njobs:\n  contract:\n    steps: []\n"
            "env:\n  not-a-job: value\n"
        )
        self.assertEqual(set(bodies), {"contract"})


if __name__ == "__main__":
    unittest.main()
