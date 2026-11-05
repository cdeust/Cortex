"""Mutation testing is scoped to the functions a pull request changes (ADR-1122)."""

from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_mutation_diff as cmd  # noqa: E402
import mutation_equivalents as eq  # noqa: E402

DIFF = textwrap.dedent(
    """\
    diff --git a/mcp_server/core/a.py b/mcp_server/core/a.py
    --- a/mcp_server/core/a.py
    +++ b/mcp_server/core/a.py
    @@ -3,0 +4,2 @@ def f
    +x
    +y
    @@ -10 +12 @@
    -old
    +new
    @@ -20,2 +22,0 @@
    -gone
    diff --git a/tests_py/core/test_a.py b/tests_py/core/test_a.py
    --- a/tests_py/core/test_a.py
    +++ b/tests_py/core/test_a.py
    @@ -1 +1 @@
    +ignored
    diff --git a/mcp_server/core/readme.md b/mcp_server/core/readme.md
    +++ b/mcp_server/core/readme.md
    @@ -1 +1 @@
    """
)

SOURCE = textwrap.dedent(
    """\
    X = 1


    def top(a):
        def inner():
            return a
        return inner()


    class K:
        def m(self):
            return 1

        async def n(self):
            return 2


    def untouched():
        return 3
    """
)


class ChangedLinesTests(unittest.TestCase):
    def test_added_modified_and_deleted_lines_of_python_sources_only(self):
        lines = cmd.changed_lines(DIFF)
        self.assertEqual(list(lines), ["mcp_server/core/a.py"])
        self.assertEqual(lines["mcp_server/core/a.py"], {4, 5, 12, 22, 23})

    def test_a_single_line_hunk_has_an_implicit_count_of_one(self):
        diff = "+++ b/mcp_server/x.py\n@@ -5 +7 @@\n"
        self.assertEqual(cmd.changed_lines(diff), {"mcp_server/x.py": {7}})


class TouchedPrefixesTests(unittest.TestCase):
    def prefixes(self, *lines):
        return cmd.touched_prefixes(SOURCE, set(lines), "mcp_server.m")

    def test_a_line_in_a_nested_function_selects_the_outer_function(self):
        self.assertEqual(self.prefixes(6), ["mcp_server.m.x_top__mutmut_"])

    def test_methods_use_the_class_qualified_mutmut_name(self):
        self.assertEqual(self.prefixes(12), ["mcp_server.m.xǁKǁm__mutmut_"])
        self.assertEqual(self.prefixes(15), ["mcp_server.m.xǁKǁn__mutmut_"])

    def test_module_level_lines_select_nothing(self):
        self.assertEqual(self.prefixes(1), [])

    def test_only_the_touched_functions_are_selected(self):
        self.assertNotIn("mcp_server.m.x_untouched__mutmut_", self.prefixes(4, 12))

    def test_package_init_names_the_package(self):
        self.assertEqual(
            cmd.module_name("mcp_server/core/__init__.py"), "mcp_server.core"
        )
        self.assertEqual(cmd.module_name("mcp_server/core/a.py"), "mcp_server.core.a")


class ScopeTests(unittest.TestCase):
    def test_no_prefix_means_everything_is_in_scope(self):
        self.assertTrue(cmd.in_scope("any.name", []))

    def test_a_prefix_keeps_only_its_own_mutants(self):
        prefixes = ["m.x_f__mutmut_"]
        self.assertTrue(cmd.in_scope("m.x_f__mutmut_3", prefixes))
        self.assertFalse(cmd.in_scope("m.x_g__mutmut_3", prefixes))
        self.assertFalse(cmd.in_scope("m.x_ff__mutmut_3", ["m.x_f__mutmut_"]))

    def test_scope_is_read_from_the_environment(self):
        env = {cmd.SCOPE_ENV: "a\nb\n"}
        self.assertEqual(cmd.scope_prefixes(env), ["a", "b"])
        self.assertEqual(cmd.scope_prefixes({}), [])

    def test_the_equivalents_gate_imports_the_same_scope_helpers(self):
        self.assertIs(eq.in_scope, cmd.in_scope)
        self.assertIs(eq.scope_prefixes, cmd.scope_prefixes)


class PlanTests(unittest.TestCase):
    def tree(self, with_test):
        root = Path(tempfile.mkdtemp())
        (root / "mcp_server/core").mkdir(parents=True)
        (root / "mcp_server/core/a.py").write_text("def f():\n    return 1\n")
        (root / "tests_py").mkdir()
        if with_test:
            (root / "tests_py/test_a.py").write_text("from mcp_server.core import a\n")
        return root

    DIFF = "+++ b/mcp_server/core/a.py\n@@ -1 +1 @@\n"

    def test_a_changed_function_gets_its_importing_tests(self):
        jobs, problems = cmd.plan(self.DIFF, self.tree(True))
        self.assertEqual(problems, [])
        self.assertEqual(jobs[0]["prefixes"], ["mcp_server.core.a.x_f__mutmut_"])
        self.assertEqual(jobs[0]["tests"][0].endswith("test_a.py"), True)

    def test_a_changed_function_without_a_test_is_a_failure(self):
        jobs, problems = cmd.plan(self.DIFF, self.tree(False))
        self.assertEqual(jobs, [])
        self.assertIn("no test file imports mcp_server.core.a", problems[0])


class SelectTestsTests(unittest.TestCase):
    def test_tests_of_scripts_and_integration_are_not_unit_tests(self):
        root = Path(tempfile.mkdtemp())
        for sub in ("core", "scripts", "integration"):
            (root / "tests_py" / sub).mkdir(parents=True)
            (root / "tests_py" / sub / "test_a.py").write_text(
                "import mcp_server.core.a\n"
            )
        chosen = cmd.select_tests("mcp_server.core.a", root / "tests_py", root)
        self.assertEqual(chosen, ["tests_py/core/test_a.py"])


class WiringTests(unittest.TestCase):
    def test_the_unit_script_runs_the_diff_mutation_step_last(self):
        text = (ROOT / "scripts/ci_unit.sh").read_text().rstrip().splitlines()
        self.assertIn("ci_mutation_diff.py", text[-1])
        self.assertTrue(any("pytest" in line for line in text[:-1]))

    def test_outside_a_pull_request_the_step_is_a_no_op(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"GITHUB_BASE_REF": ""}):
            self.assertEqual(cmd.main([]), 0)


if __name__ == "__main__":
    unittest.main()
