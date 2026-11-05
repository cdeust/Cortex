"""Edge cases of the changed-function mutation gate (ADR-1122): imports, deletions,
mutants no test reaches, and the diff perimeter."""

from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_mutation_diff as cmd  # noqa: E402


class SelectTestsImportFormsTests(unittest.TestCase):
    def chosen(self, source):
        root = Path(tempfile.mkdtemp())
        (root / "tests_py").mkdir()
        (root / "tests_py" / "test_a.py").write_text(source)
        return cmd.select_tests("mcp_server.handlers.wiki", root / "tests_py", root)

    def test_a_parenthesized_multiline_import_selects_the_test(self):
        source = "from mcp_server.handlers import (\n    other,\n    wiki,\n)\n"
        self.assertEqual(self.chosen(source), ["tests_py/test_a.py"])

    def test_a_one_line_and_a_dotted_import_select_the_test(self):
        self.assertTrue(self.chosen("from mcp_server.handlers import wiki\n"))
        self.assertTrue(self.chosen("import mcp_server.handlers.wiki as w\n"))
        self.assertTrue(self.chosen("from mcp_server.handlers.wiki import f\n"))

    def test_a_name_in_a_comment_or_a_string_does_not_select_it(self):
        self.assertEqual(self.chosen("# mcp_server.handlers.wiki\nX = 'wiki'\n"), [])

    def test_a_longer_module_name_is_not_a_match(self):
        self.assertEqual(self.chosen("import mcp_server.handlers.wiki_extra\n"), [])


class DeletionTests(unittest.TestCase):
    SRC = textwrap.dedent(
        """\
        def f(x):
            if x:
                return 1

        def g():
            return 3
        """
    )

    def test_a_deleted_last_statement_selects_the_shortened_function(self):
        self.assertEqual(cmd.touched_prefixes(self.SRC, {3}, "m"), ["m.x_f__mutmut_"])

    def test_a_function_owns_the_blank_line_after_it(self):
        # `return 2` was deleted; git anchors on the blank line 4 after f ends.
        self.assertEqual(cmd.touched_prefixes(self.SRC, {4}, "m"), ["m.x_f__mutmut_"])

    def test_the_last_method_of_a_class_does_not_own_the_code_after_it(self):
        src = (
            "class K:\n    def n(self):\n        return 1\n\n\n"
            "def bar():\n    return 2\n"
        )
        self.assertEqual(cmd.touched_prefixes(src, {7}, "m"), ["m.x_bar__mutmut_"])
        self.assertEqual(cmd.touched_prefixes(src, {4}, "m"), ["m.xǁKǁn__mutmut_"])

    def test_a_deleted_lone_decorator_keeps_its_function(self):
        diff = "+++ b/mcp_server/m.py\n@@ -10 +9,0 @@\n-@functools.cache\n"
        self.assertEqual(cmd.changed_lines(diff), {"mcp_server/m.py": {9, 10}})

    def test_a_deleted_decorated_definition_selects_nothing(self):
        diff = (
            "+++ b/mcp_server/m.py\n@@ -10,3 +9,0 @@\n"
            "-@functools.cache\n-def h():\n-    return 9\n"
        )
        self.assertEqual(cmd.changed_lines(diff), {})

    def test_a_deleted_whole_function_selects_nothing(self):
        diff = "+++ b/mcp_server/m.py\n@@ -5,2 +4,0 @@\n-def h():\n-    return 9\n"
        self.assertEqual(cmd.changed_lines(diff), {})

    def test_a_deleted_body_statement_is_kept(self):
        diff = "+++ b/mcp_server/m.py\n@@ -4 +3,0 @@\n-        return 2\n"
        self.assertEqual(cmd.changed_lines(diff), {"mcp_server/m.py": {3, 4}})

    def test_a_changed_decorator_selects_its_function(self):
        src = "import a\n\n@a.b\ndef f():\n    return 1\n"
        self.assertEqual(cmd.touched_prefixes(src, {3}, "m"), ["m.x_f__mutmut_"])


class UntestedMutantTests(unittest.TestCase):
    RESULTS = (
        "    m.x_f__mutmut_1: killed\n"
        "    m.x_f__mutmut_2: no tests\n"
        "    m.x_g__mutmut_1: no tests\n"
        "    m.x_f__mutmut_3: timeout\n"
    )

    def test_unchecked_and_crashed_mutants_are_not_killed_either(self):
        results = "    m.x_f__mutmut_1: not checked\n    m.x_f__mutmut_2: segfault\n"
        self.assertEqual(len(cmd.untested(results, [])), 2)

    def test_in_scope_mutants_no_test_reaches_are_reported(self):
        self.assertEqual(
            cmd.untested(self.RESULTS, ["m.x_f__mutmut_"]),
            ["m.x_f__mutmut_2", "m.x_f__mutmut_3"],
        )

    def test_the_cli_mode_fails_only_inside_a_scope(self):
        import io
        import os
        from unittest import mock

        with mock.patch("sys.stdin", io.StringIO(self.RESULTS)):
            with mock.patch.dict(os.environ, {cmd.SCOPE_ENV: "m.x_f__mutmut_"}):
                self.assertEqual(cmd.main(["--untested"]), 1)
        with mock.patch("sys.stdin", io.StringIO(self.RESULTS)):
            with mock.patch.dict(os.environ, {cmd.SCOPE_ENV: ""}):
                self.assertEqual(cmd.main(["--untested"]), 0)

    def test_mutation_check_runs_the_untested_gate_and_serializes_workers(self):
        text = (ROOT / "scripts/mutation_check.sh").read_text()
        self.assertIn('ci_mutation_diff.py" --untested', text)
        self.assertIn("--max-children", text)
        job = {"file": "f.py", "tests": ["t.py"], "prefixes": ["p"]}
        from unittest import mock

        with mock.patch.object(cmd.subprocess, "run") as run:
            run.return_value.returncode = 0
            cmd.run_job(job)
        self.assertEqual(run.call_args.kwargs["env"][cmd.MAX_CHILDREN_ENV], "1")


class BaseDiffTests(unittest.TestCase):
    """The perimeter is the merge base, so a base that moves on adds nothing."""

    def git(self, cwd, *args):
        import subprocess

        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
        )

    def test_a_base_branch_that_advanced_is_not_part_of_the_diff(self):
        from unittest import mock

        origin = Path(tempfile.mkdtemp())
        self.git(origin, "init", "-q", "-b", "main")
        (origin / "mcp_server").mkdir()
        (origin / "mcp_server" / "m.py").write_text(
            "def f():\n    return 1\n\n\ndef g():\n    return 1\n"
        )
        self.git(origin, "add", ".")
        self.git(origin, "commit", "-qm", "base")
        clone = Path(tempfile.mkdtemp()) / "c"
        self.git(origin, "clone", "-q", str(origin), str(clone))
        self.git(clone, "checkout", "-qb", "pr")
        (clone / "mcp_server" / "m.py").write_text(
            "def f():\n    return 2\n\n\ndef g():\n    return 1\n"
        )
        self.git(clone, "commit", "-qam", "pr")
        (origin / "mcp_server" / "m.py").write_text(
            "def f():\n    return 1\n\n\ndef g():\n    return 9\n"
        )
        self.git(origin, "commit", "-qam", "main moves on")
        with mock.patch.object(cmd, "ROOT", clone):
            diff = cmd.base_diff("main")
        self.assertEqual(cmd.changed_lines(diff), {"mcp_server/m.py": {2}})


if __name__ == "__main__":
    unittest.main()
