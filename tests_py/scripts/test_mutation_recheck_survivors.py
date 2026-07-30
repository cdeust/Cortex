"""Tests for scripts/mutation_recheck_survivors.py — issue #269.

Root cause under test: mutmut's per-mutant test attribution is recorded
once, from a coverage trace of the FIRST test to reach a mutated line. A
module that builds a dispatch table eagerly at import time (memoizing
closures) makes every later test invisible to that attribution, so
mutmut narrows the per-mutant rerun to just the first test and reports
"survived" even when the full suite kills the mutant. This module's job
is to catch that: re-run every mutmut-reported survivor against the full
test selection before trusting the verdict.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Dotted to match the path-derived name mutmut keys mutant trampolines on
# ("scripts.mutation_recheck_survivors.*") — issue #262/#264 precedent.
_spec = importlib.util.spec_from_file_location(
    "scripts.mutation_recheck_survivors",
    REPO / "scripts" / "mutation_recheck_survivors.py",
)
mrs = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mrs
_spec.loader.exec_module(mrs)


class ParseSurvivorsTests(unittest.TestCase):
    def test_extracts_only_survived_lines(self) -> None:
        output = (
            "    pkg.mod.x_foo__mutmut_1: killed\n"
            "    pkg.mod.x_foo__mutmut_2: survived\n"
            "    pkg.mod.x_bar__mutmut_1: no tests\n"
        )
        self.assertEqual(mrs.parse_survivors(output), ["pkg.mod.x_foo__mutmut_2"])

    def test_no_survived_lines_yields_empty_list(self) -> None:
        self.assertEqual(
            mrs.parse_survivors("    pkg.mod.x_foo__mutmut_1: killed\n"), []
        )

    def test_empty_input_yields_empty_list(self) -> None:
        self.assertEqual(mrs.parse_survivors(""), [])

    def test_duplicate_survived_lines_are_deduplicated_in_order(self) -> None:
        output = (
            "    pkg.mod.x_a__mutmut_1: survived\n"
            "    pkg.mod.x_b__mutmut_1: survived\n"
            "    pkg.mod.x_a__mutmut_1: survived\n"
        )
        self.assertEqual(
            mrs.parse_survivors(output),
            ["pkg.mod.x_a__mutmut_1", "pkg.mod.x_b__mutmut_1"],
        )

    def test_status_containing_survived_as_a_substring_is_not_matched(self) -> None:
        # Regression guard for a naive `"survived" in line` check, which
        # would also match a hypothetical "not survived" or similar status.
        self.assertEqual(
            mrs.parse_survivors("    pkg.mod.x_a__mutmut_1: not survived\n"), []
        )


class RecheckSurvivorTests(unittest.TestCase):
    def test_pytest_exit_zero_means_genuinely_survived(self) -> None:
        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001 — test double, signature matches Runner
            return subprocess.CompletedProcess(cmd, returncode=0)

        outcome = mrs.recheck_survivor(
            "pkg.mod.x_foo__mutmut_1",
            ["tests/test_foo.py"],
            mutants_dir=Path("/tmp/mutants"),
            base_env={},
            runner=fake_runner,
        )
        self.assertTrue(outcome.genuinely_survived)
        self.assertEqual(outcome.exit_code, 0)

    def test_pytest_nonzero_exit_means_recovered_not_genuine(self) -> None:
        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            return subprocess.CompletedProcess(cmd, returncode=1)

        outcome = mrs.recheck_survivor(
            "pkg.mod.x_foo__mutmut_1",
            ["tests/test_foo.py"],
            mutants_dir=Path("/tmp/mutants"),
            base_env={},
            runner=fake_runner,
        )
        self.assertFalse(outcome.genuinely_survived)
        self.assertEqual(outcome.exit_code, 1)

    def test_mutant_under_test_env_var_is_set_to_the_mutant_name(self) -> None:
        captured: dict[str, object] = {}

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            captured["env"] = env
            return subprocess.CompletedProcess(cmd, returncode=0)

        mrs.recheck_survivor(
            "pkg.mod.x_foo__mutmut_7",
            ["tests/test_foo.py"],
            mutants_dir=Path("/tmp/mutants"),
            base_env={"PATH": "/usr/bin"},
            runner=fake_runner,
        )
        self.assertEqual(
            captured["env"]["MUTANT_UNDER_TEST"], "pkg.mod.x_foo__mutmut_7"
        )
        # base_env must not be mutated in place, and its other keys preserved.
        self.assertEqual(captured["env"]["PATH"], "/usr/bin")

    def test_base_env_dict_passed_in_is_not_mutated(self) -> None:
        base_env = {"PATH": "/usr/bin"}

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            return subprocess.CompletedProcess(cmd, returncode=0)

        mrs.recheck_survivor(
            "pkg.mod.x_foo__mutmut_1",
            ["tests/test_foo.py"],
            mutants_dir=Path("/tmp/mutants"),
            base_env=base_env,
            runner=fake_runner,
        )
        self.assertEqual(base_env, {"PATH": "/usr/bin"})

    def test_the_full_command_is_python_dash_m_pytest_dash_q_plus_tests(self) -> None:
        # Exact equality, not a suffix check: every fixed token ("-m",
        # "pytest", "-q") is load-bearing and a lone suffix assertion
        # would leave each one an unkilled mutant.
        captured: dict[str, object] = {}

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, returncode=0)

        mrs.recheck_survivor(
            "pkg.mod.x_foo__mutmut_1",
            ["tests/test_a.py", "tests/test_b.py"],
            mutants_dir=Path("/tmp/mutants"),
            base_env={},
            runner=fake_runner,
        )
        self.assertEqual(
            captured["cmd"],
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_a.py",
                "tests/test_b.py",
            ],
        )

    def test_the_runner_is_invoked_with_mutants_dir_as_cwd(self) -> None:
        captured: dict[str, object] = {}

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            captured["cwd"] = cwd
            return subprocess.CompletedProcess(cmd, returncode=0)

        mutants_dir = Path("/tmp/mutants-xyz")
        mrs.recheck_survivor(
            "pkg.mod.x_foo__mutmut_1",
            ["tests/test_a.py"],
            mutants_dir=mutants_dir,
            base_env={},
            runner=fake_runner,
        )
        self.assertEqual(captured["cwd"], mutants_dir)

    def test_the_outcome_carries_the_input_mutant_name_back(self) -> None:
        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            return subprocess.CompletedProcess(cmd, returncode=0)

        outcome = mrs.recheck_survivor(
            "pkg.mod.x_foo__mutmut_42",
            ["tests/test_a.py"],
            mutants_dir=Path("/tmp/mutants"),
            base_env={},
            runner=fake_runner,
        )
        self.assertEqual(outcome.mutant_name, "pkg.mod.x_foo__mutmut_42")


class RecheckAllSurvivorsTests(unittest.TestCase):
    def test_empty_survivors_list_short_circuits_without_calling_the_runner(
        self,
    ) -> None:
        calls: list[object] = []

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0)

        outcomes = mrs.recheck_all_survivors(
            [],
            [],
            mutants_dir=Path("/tmp/mutants"),
            base_env={},
            runner=fake_runner,
        )
        self.assertEqual(outcomes, [])
        self.assertEqual(calls, [])

    def test_nonempty_survivors_with_empty_test_selection_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            mrs.recheck_all_survivors(
                ["pkg.mod.x_foo__mutmut_1"],
                [],
                mutants_dir=Path("/tmp/mutants"),
                base_env={},
            )
        self.assertEqual(
            str(ctx.exception),
            "full_test_selection must be non-empty to recheck survivors",
        )

    def test_each_survivor_is_rechecked_independently(self) -> None:
        # mutant_1 recovered (pytest catches it), mutant_2 genuine survivor.
        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            return subprocess.CompletedProcess(
                cmd, returncode=1 if env["MUTANT_UNDER_TEST"].endswith("_1") else 0
            )

        outcomes = mrs.recheck_all_survivors(
            ["pkg.mod.x_foo__mutmut_1", "pkg.mod.x_foo__mutmut_2"],
            ["tests/test_foo.py"],
            mutants_dir=Path("/tmp/mutants"),
            base_env={},
            runner=fake_runner,
        )
        self.assertEqual(len(outcomes), 2)
        self.assertFalse(outcomes[0].genuinely_survived)
        self.assertTrue(outcomes[1].genuinely_survived)

    def test_mutants_dir_is_forwarded_to_every_recheck_call(self) -> None:
        captured_cwds: list[object] = []

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            captured_cwds.append(cwd)
            return subprocess.CompletedProcess(cmd, returncode=0)

        real_mutants_dir = Path("/tmp/real-mutants-dir")
        mrs.recheck_all_survivors(
            ["pkg.mod.x_foo__mutmut_1", "pkg.mod.x_foo__mutmut_2"],
            ["tests/test_foo.py"],
            mutants_dir=real_mutants_dir,
            base_env={},
            runner=fake_runner,
        )
        self.assertEqual(captured_cwds, [real_mutants_dir, real_mutants_dir])


class AnyGenuineSurvivorsTests(unittest.TestCase):
    def test_empty_outcomes_is_false(self) -> None:
        self.assertFalse(mrs.any_genuine_survivors([]))

    def test_all_recovered_is_false(self) -> None:
        outcomes = [mrs.RecheckOutcome("m1", genuinely_survived=False, exit_code=1)]
        self.assertFalse(mrs.any_genuine_survivors(outcomes))

    def test_one_genuine_is_true(self) -> None:
        outcomes = [
            mrs.RecheckOutcome("m1", genuinely_survived=False, exit_code=1),
            mrs.RecheckOutcome("m2", genuinely_survived=True, exit_code=0),
        ]
        self.assertTrue(mrs.any_genuine_survivors(outcomes))


class FormatReportTests(unittest.TestCase):
    def test_empty_outcomes_reports_nothing_to_recheck(self) -> None:
        # Exact equality: a substring check like assertIn("none", ...)
        # survives a case/wording mutation of the rest of the literal.
        self.assertEqual(
            mrs.format_report([]),
            "  none — 0 mutmut-reported survivors to recheck",
        )

    def test_all_recovered_names_issue_269_and_lists_each_mutant(self) -> None:
        outcomes = [
            mrs.RecheckOutcome("m1", genuinely_survived=False, exit_code=1),
            mrs.RecheckOutcome("m2", genuinely_survived=False, exit_code=3),
        ]
        report = mrs.format_report(outcomes)
        self.assertEqual(
            report,
            "\n".join(
                [
                    ">>> 2 mutmut-reported survivor(s) RECOVERED: killed by "
                    "the full test selection, invisible to mutmut's per-mutant "
                    "test attribution (eager module-level dispatch table — "
                    "see issue #269):",
                    "    m1 (pytest exit 1)",
                    "    m2 (pytest exit 3)",
                    ">>> 0 genuine survivors after full-selection reverification 🎉",
                ]
            ),
        )

    def test_a_genuine_survivor_is_never_absorbed_into_the_recovered_section(
        self,
    ) -> None:
        outcomes = [
            mrs.RecheckOutcome("recovered_one", genuinely_survived=False, exit_code=1),
            mrs.RecheckOutcome("genuine_one", genuinely_survived=True, exit_code=0),
        ]
        report = mrs.format_report(outcomes)
        recovered_section, _, genuine_section = report.partition("GENUINE")
        self.assertIn("recovered_one", recovered_section)
        self.assertNotIn("genuine_one", recovered_section)
        self.assertIn("genuine_one", genuine_section)

    def test_all_genuine_no_recovered_section_at_all(self) -> None:
        # Exact equality pins the "GENUINE surviving mutant(s)" wording AND
        # that no RECOVERED section (nor the "0 genuine" fallback line,
        # which only applies when genuine is empty) appears.
        outcomes = [mrs.RecheckOutcome("m1", genuinely_survived=True, exit_code=0)]
        report = mrs.format_report(outcomes)
        self.assertEqual(
            report,
            "\n".join(
                [
                    ">>> 1 GENUINE surviving mutant(s) — a real test gap:",
                    "    m1",
                ]
            ),
        )


class MainCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_stdin = sys.stdin

    def tearDown(self) -> None:
        sys.stdin = self._old_stdin

    def test_missing_args_prints_usage_and_returns_2(self) -> None:
        self.assertEqual(mrs._main([]), 2)

    def test_a_single_arg_is_still_missing_args(self) -> None:
        # Regression guard for `len(argv) < 2` weakening to `< 1` or `<= 1`
        # meaning something other than "need mutants_dir + >=1 test path".
        self.assertEqual(mrs._main(["/tmp/mutants"]), 2)

    def test_missing_args_prints_the_exact_usage_line_to_stderr(self) -> None:
        # Exact equality: assertIn("usage:", ...) still passes against a
        # mutated middle segment of the same literal (e.g. an "XX"-wrapped
        # or upper-cased fragment mutmut generates), since "usage:" and
        # the module name survive untouched either way.
        captured_stderr = io.StringIO()
        with contextlib.redirect_stderr(captured_stderr):
            mrs._main([])
        self.assertEqual(
            captured_stderr.getvalue(),
            "usage: mutation_recheck_survivors.py <mutants_dir> <test_path> "
            "[test_path ...]   (reads `mutmut results` output on stdin)\n",
        )

    def test_no_survivors_on_stdin_returns_0_without_a_runner_call(self) -> None:
        calls: list[object] = []

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0)

        sys.stdin = io.StringIO("    pkg.mod.x_a__mutmut_1: killed\n")
        result = mrs._main(["/tmp/mutants", "tests/test_a.py"], runner=fake_runner)
        self.assertEqual(result, 0)
        self.assertEqual(calls, [])

    def test_a_recovered_survivor_on_stdin_returns_0(self) -> None:
        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            return subprocess.CompletedProcess(
                cmd, returncode=1
            )  # killed by full selection

        sys.stdin = io.StringIO("    pkg.mod.x_a__mutmut_1: survived\n")
        result = mrs._main(["/tmp/mutants", "tests/test_a.py"], runner=fake_runner)
        self.assertEqual(result, 0)

    def test_a_genuine_survivor_on_stdin_returns_1(self) -> None:
        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            return subprocess.CompletedProcess(
                cmd, returncode=0
            )  # still passes -> genuine

        sys.stdin = io.StringIO("    pkg.mod.x_a__mutmut_1: survived\n")
        result = mrs._main(["/tmp/mutants", "tests/test_a.py"], runner=fake_runner)
        self.assertEqual(result, 1)

    def test_mutants_dir_argv0_is_forwarded_to_the_runner_as_cwd(self) -> None:
        captured: dict[str, object] = {}

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            captured["cwd"] = cwd
            return subprocess.CompletedProcess(cmd, returncode=0)

        sys.stdin = io.StringIO("    pkg.mod.x_a__mutmut_1: survived\n")
        mrs._main(["/tmp/mutants-abc", "tests/test_a.py"], runner=fake_runner)
        self.assertEqual(captured["cwd"], Path("/tmp/mutants-abc"))

    def test_all_argv_after_mutants_dir_are_the_test_selection(self) -> None:
        captured: dict[str, object] = {}

        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, returncode=0)

        sys.stdin = io.StringIO("    pkg.mod.x_a__mutmut_1: survived\n")
        mrs._main(
            ["/tmp/mutants", "tests/test_a.py", "tests/test_b.py"], runner=fake_runner
        )
        self.assertEqual(captured["cmd"][-2:], ["tests/test_a.py", "tests/test_b.py"])

    def test_the_recheck_report_is_actually_printed_to_stdout(self) -> None:
        # Regression guard for `print(None)` or `format_report(None)`
        # silently replacing the real, computed report.
        def fake_runner(cmd, env, cwd):  # noqa: ANN001, ARG001
            return subprocess.CompletedProcess(cmd, returncode=0)

        sys.stdin = io.StringIO("    pkg.mod.x_a__mutmut_1: survived\n")
        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            mrs._main(["/tmp/mutants", "tests/test_a.py"], runner=fake_runner)
        self.assertEqual(
            captured_stdout.getvalue().rstrip("\n"),
            mrs.format_report(
                [
                    mrs.RecheckOutcome(
                        "pkg.mod.x_a__mutmut_1", genuinely_survived=True, exit_code=0
                    )
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
