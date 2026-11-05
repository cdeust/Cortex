"""Deletion edge cases of the changed-function mutation gate (ADR-1122): a note above a
removed method, the next file's header after a hunk, `plan()` on a lone method
removal, and decorated or async nested functions."""

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_diff_lines as cdl  # noqa: E402
import ci_mutation_diff as cmd  # noqa: E402

PATH = "mcp_server/m.py"
CLASS = (
    "class K:\n    def a(self):\n        return 1\n\n"
    "    def c(self):\n        return 3\n"
)


def diff(hunk):
    return f"+++ b/{PATH}\n{hunk}"


class NoteAndHeaderTests(unittest.TestCase):
    def test_a_comment_above_a_removed_method_does_not_select_its_neighbours(self):
        lines, cuts = cdl.changed_lines_ex(
            diff(
                "@@ -5,4 +4,0 @@\n-    # note\n-    def b(self):\n"
                "-        return 2\n-\n"
            )
        )
        self.assertEqual(lines, {})
        self.assertEqual(cuts, {PATH: {(4, 4)}})
        self.assertEqual(cmd.touched_prefixes(CLASS, set(), "m", cuts[PATH]), [])

    def test_the_next_files_header_does_not_hide_a_trailing_decorator(self):
        lines, _ = cdl.changed_lines_ex(
            diff(
                "@@ -5,3 +4,0 @@\n-def b():\n-    return 2\n-@dec\n"
                "--- a/mcp_server/n.py\n+++ b/mcp_server/n.py\n@@ -1 +1 @@\n-x\n+y\n"
            )
        )
        self.assertEqual(lines, {PATH: {5}, "mcp_server/n.py": {1}})

    def test_a_git_header_closes_the_open_hunk(self):
        lines, _ = cdl.changed_lines_ex(
            diff(
                "@@ -5,2 +4,0 @@\n-def b():\n-    return 2\n"
                "diff --git a/mcp_server/n.py b/mcp_server/n.py\n"
                "--- a/mcp_server/n.py\n+++ b/mcp_server/n.py\n@@ -1 +1 @@\n-x\n+y\n"
            )
        )
        self.assertEqual(lines, {"mcp_server/n.py": {1}})


class PlanAndNestedTests(unittest.TestCase):
    def test_plan_runs_nothing_when_the_only_change_removes_a_whole_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mcp_server").mkdir()
            (root / PATH).write_text(CLASS)
            (root / "tests_py").mkdir()
            (root / "tests_py" / "test_m.py").write_text("import mcp_server.m\n")
            jobs, problems = cmd.plan(
                diff("@@ -5,3 +4,0 @@\n-    def b(self):\n-        return 2\n-\n"), root
            )
        self.assertEqual((jobs, problems), ([], []))

    def test_a_decorated_async_nested_function_removed_selects_its_function(self):
        src = "def f():\n    x = 1\n    return x\n"
        _, cuts = cdl.changed_lines_ex(
            diff(
                "@@ -2,3 +1,0 @@\n-    @deco\n-    async def g():\n-        return 2\n"
            )
        )
        self.assertEqual(
            cmd.touched_prefixes(src, set(), "m", cuts[PATH]), ["m.x_f__mutmut_"]
        )


if __name__ == "__main__":
    unittest.main()
