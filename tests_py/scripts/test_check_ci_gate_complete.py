"""Tests for scripts/check_ci_gate_complete.py — the aggregate-CI-gate guard.

Branch protection names one status check, ``CI Green``, and the real list of
gated jobs lives in that job's ``needs:``. This guard is the only thing
standing between that design and its failure mode: a job added to ci.yml but
never added to ``needs`` runs outside the gate and can fail without blocking
a merge — silently, exactly like the eleven-context arrangement it replaced.

So the guard's own failure mode is silence. Each check below is pinned by a
fixture that must FAIL, plus a live assertion that the repository's real
ci.yml passes — a parser that quietly stopped matching would otherwise be
indistinguishable from a clean tree.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

# Dotted, path-derived module name: mutmut keys its trampolines on
# "scripts.check_ci_gate_complete.*" and a bare name makes every mutant look
# unreached (issue #293, same idiom as test_check_doc_claims.py).
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_spec = importlib.util.spec_from_file_location(
    "scripts.check_ci_gate_complete", _SCRIPTS / "check_ci_gate_complete.py"
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _workflow(jobs: str) -> str:
    """Wrap job definitions in the minimal ci.yml envelope the parser reads."""
    return "name: CI\n\non:\n  push:\n    branches: [main]\n\njobs:\n" + jobs


_COMPLETE = _workflow(
    """  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - run: ruff check .

  mcp-host-config:
    name: Validate MCP host configurations
    runs-on: ubuntu-latest
    if: github.event.pull_request.head.repo.fork == false
    steps:
      - run: true

  ci-green:
    name: CI Green
    if: always()
    runs-on: ubuntu-latest
    needs:
      - lint
      - mcp-host-config
    steps:
      - name: Require every job above to have succeeded
        env:
          NEEDS: ${{ toJSON(needs) }}
          ALLOWED_SKIPS: mcp-host-config
        run: true
"""
)


class CheckCompleteGate(unittest.TestCase):
    def test_complete_workflow_has_no_failures(self) -> None:
        self.assertEqual(gate.check(_COMPLETE), [])

    def test_parses_jobs_needs_and_allowed_skips(self) -> None:
        jobs, needs, allowed, exempt = gate.parse_workflow(_COMPLETE)
        self.assertEqual(set(jobs), {"lint", "mcp-host-config", "ci-green"})
        self.assertFalse(jobs["lint"])
        self.assertTrue(jobs["mcp-host-config"])
        self.assertEqual(needs, ["lint", "mcp-host-config"])
        self.assertEqual(allowed, ["mcp-host-config"])
        self.assertEqual(exempt, set())


class RefusesIncompleteGate(unittest.TestCase):
    def _only_failure(self, workflow: str) -> str:
        failures = gate.check(workflow)
        self.assertEqual(len(failures), 1, failures)
        return failures[0]

    def test_missing_gate_job_fails(self) -> None:
        workflow = _workflow(
            "  lint:\n    name: Lint\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: true\n"
        )
        self.assertIn(gate.GATE_JOB, self._only_failure(workflow))

    def test_job_absent_from_needs_fails(self) -> None:
        workflow = _COMPLETE.replace("      - lint\n", "")
        self.assertIn("'lint' is not in", self._only_failure(workflow))

    def test_needs_naming_a_nonexistent_job_fails(self) -> None:
        workflow = _COMPLETE.replace("      - lint\n", "      - lint\n      - ghost\n")
        self.assertIn("'ghost'", self._only_failure(workflow))

    def test_conditional_job_missing_from_allowed_skips_fails(self) -> None:
        workflow = _COMPLETE.replace("          ALLOWED_SKIPS: mcp-host-config\n", "")
        failure = self._only_failure(workflow)
        self.assertIn("mcp-host-config", failure)
        self.assertIn("ALLOWED_SKIPS", failure)

    def test_stale_allowed_skips_entry_fails(self) -> None:
        # `lint` carries no `if:`, so exempting it guards nothing and hides a
        # real skip if one ever appears.
        workflow = _COMPLETE.replace(
            "ALLOWED_SKIPS: mcp-host-config", "ALLOWED_SKIPS: mcp-host-config, lint"
        )
        self.assertIn("'lint'", self._only_failure(workflow))

    def test_gate_must_always_run(self) -> None:
        for condition in ("", "    if: success()\n"):
            workflow = _COMPLETE.replace("    if: always()\n", condition)
            self.assertIn("always()", self._only_failure(workflow))

    def test_duplicate_or_self_needs_fail(self) -> None:
        for job in ("lint", "ci-green"):
            workflow = _COMPLETE.replace(
                "      - lint\n", f"      - lint\n      - {job}\n"
            )
            self.assertIn("dependency", self._only_failure(workflow))


_WITH_EXEMPT_JOB = _workflow(
    """  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - run: ruff check .

  mcp-host-config:
    name: Validate MCP host configurations
    runs-on: ubuntu-latest
    if: github.event.pull_request.head.repo.fork == false
    steps:
      - run: true

  release-gate:
    name: Tag a release
    needs: [ci-green]
    # ci-gate-exempt: runs only on push to main, after the PR merged —
    # there is nothing left for it to gate.
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - run: true

  ci-green:
    name: CI Green
    if: always()
    runs-on: ubuntu-latest
    needs:
      - lint
      - mcp-host-config
    steps:
      - name: Require every job above to have succeeded
        env:
          NEEDS: ${{ toJSON(needs) }}
          ALLOWED_SKIPS: mcp-host-config
        run: true
"""
)


class GateExemptJobs(unittest.TestCase):
    def test_exempt_job_outside_needs_has_no_failures(self) -> None:
        self.assertEqual(gate.check(_WITH_EXEMPT_JOB), [])

    def test_parses_exempt_set(self) -> None:
        jobs, needs, allowed, exempt = gate.parse_workflow(_WITH_EXEMPT_JOB)
        self.assertEqual(exempt, {"release-gate"})
        self.assertNotIn("release-gate", needs)
        self.assertTrue(jobs["release-gate"])

    def test_exempt_job_without_if_fails(self) -> None:
        workflow = _WITH_EXEMPT_JOB.replace(
            "    if: github.event_name == 'push' && github.ref == 'refs/heads/main'\n",
            "",
        )
        failures = gate.check(workflow)
        self.assertTrue(
            any("release-gate" in f and "no job-level" in f for f in failures),
            failures,
        )

    def test_unexempt_unneeded_job_still_fails(self) -> None:
        # Sanity: removing the marker (with no needs entry either) reverts to
        # the original "runs outside the gate" failure — the marker is a
        # deliberate escape hatch, not a parser blind spot.
        workflow = _WITH_EXEMPT_JOB.replace(
            "    # ci-gate-exempt: runs only on push to main, after the PR merged —\n"
            "    # there is nothing left for it to gate.\n",
            "",
        )
        failures = gate.check(workflow)
        unmarked = [f for f in failures if "release-gate" in f and "carries no" in f]
        self.assertTrue(unmarked, failures)


class RepositoryWorkflowIsGated(unittest.TestCase):
    def test_live_ci_workflow_passes(self) -> None:
        """The guard must agree with the tree it ships in, not just fixtures."""
        self.assertTrue(gate.CI_WORKFLOW.exists(), gate.CI_WORKFLOW)
        self.assertEqual(
            gate.check(gate.CI_WORKFLOW.read_text(encoding="utf-8")),
            [],
        )

    def test_runtime_policy_matches_live_workflow(self) -> None:
        self.assertEqual(gate.check_runtime_contract(gate.CI_WORKFLOW.read_text()), [])

    def test_costly_jobs_must_wait_for_lint_and_changes(self) -> None:
        workflow = gate.CI_WORKFLOW.read_text()
        for prerequisites in ("[changes]", "[lint]", "[changes, lint, test]"):
            changed = workflow.replace("[changes, lint]", prerequisites, 1)
            failures = gate.check_runtime_contract(changed)
            self.assertTrue(any("depend on exactly" in f for f in failures))

    def test_lint_and_changes_cannot_be_conditional(self) -> None:
        workflow = gate.CI_WORKFLOW.read_text()
        for job in ("changes", "lint"):
            changed = workflow.replace(f"  {job}:\n", f"  {job}:\n    if: false\n")
            self.assertTrue(gate.check_runtime_contract(changed))

    def test_new_skip_needs_an_executable_policy(self) -> None:
        workflow = gate.CI_WORKFLOW.read_text()
        workflow = workflow.replace(
            "ALLOWED_SKIPS: test,", "ALLOWED_SKIPS: unknown-job,test,"
        )
        failures = gate.check_runtime_contract(workflow)
        self.assertTrue(any("runtime skip policy" in f for f in failures))


if __name__ == "__main__":
    unittest.main()
