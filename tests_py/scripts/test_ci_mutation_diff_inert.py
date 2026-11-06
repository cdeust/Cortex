"""Added blank and comment-only lines touch no function (ADR-1122).

#878 added `timed_stage` below `count_reranked`. The two blank lines between them fall
in the span `_span` gives `count_reranked`, so the gate judged a function the PR did
not change. A blank or comment line inside a multiline string still changes it.
"""

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_mutation_diff as cmd  # noqa: E402

PATH = "mcp_server/m.py"


def _plan(source: str, hunk: str) -> list[list[str]]:
    """The prefixes `plan()` gates for `hunk` on `source`; one test imports m."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "mcp_server").mkdir()
        (root / PATH).write_text(source, encoding="utf-8")
        (root / "tests_py").mkdir()
        (root / "tests_py" / "test_m.py").write_text(
            "import mcp_server.m\n", encoding="utf-8"
        )
        jobs, problems = cmd.plan(f"+++ b/{PATH}\n{hunk}", root)
    assert problems == []
    return [job["prefixes"] for job in jobs]


class InertLineTests(unittest.TestCase):
    def test_a_new_function_below_does_not_touch_the_one_above(self):
        src = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
        # b and the two blank lines above it were added after a.
        self.assertEqual(
            _plan(src, "@@ -2,0 +3,4 @@\n+\n+\n+def b():\n+    return 2\n"),
            [["mcp_server.m.x_b__mutmut_"]],
        )

    def test_an_added_comment_inside_a_function_touches_nothing(self):
        src = "def a():\n    # why\n    return 1\n"
        self.assertEqual(_plan(src, "@@ -1,0 +2 @@\n+    # why\n"), [])

    def test_code_replaced_by_a_comment_still_touches_its_function(self):
        src = "def a():\n    # x = 1\n    return 1\n"
        self.assertEqual(
            _plan(src, "@@ -2 +2 @@\n-    x = 1\n+    # x = 1\n"),
            [["mcp_server.m.x_a__mutmut_"]],
        )

    def test_a_blank_line_inside_a_multiline_string_touches_its_function(self):
        src = 'def a():\n    return """x\n\n# y\n"""\n'
        self.assertEqual(
            _plan(src, "@@ -2,0 +3,2 @@\n+\n+# y\n"),
            [["mcp_server.m.x_a__mutmut_"]],
        )

    def test_a_blank_line_inside_a_multiline_bytes_literal_touches_its_function(self):
        src = 'def a():\n    return b"""x\n\n"""\n'
        self.assertEqual(
            _plan(src, "@@ -2,0 +3 @@\n+\n"), [["mcp_server.m.x_a__mutmut_"]]
        )

    def test_a_blank_line_inside_a_multiline_f_string_touches_its_function(self):
        src = 'def a(v):\n    return f"""{v}\n\n"""\n'
        self.assertEqual(
            _plan(src, "@@ -2,0 +3 @@\n+\n"), [["mcp_server.m.x_a__mutmut_"]]
        )

    def test_a_comment_replaced_by_code_and_a_blank_touches_its_function(self):
        src = "def a():\n    x = 1\n\n    return x\n"
        self.assertEqual(
            _plan(src, "@@ -2 +2,2 @@\n-    # x\n+    x = 1\n+\n"),
            [["mcp_server.m.x_a__mutmut_"]],
        )

    def test_a_form_feed_inside_an_added_line_does_not_shift_the_next_lines(self):
        # str.splitlines() would cut `+Y = '\x0c+#'` in two, and the extra `+#'`
        # piece would shift `def b():` onto an inert position and drop it.
        src = "X = 1\nY = '\x0c+#'\n\n\ndef b():\n    return 2\n"
        hunk = "@@ -1,0 +2,4 @@\n+Y = '\x0c+#'\n+\n+\n+def b():\n"
        self.assertEqual(_plan(src, hunk), [["mcp_server.m.x_b__mutmut_"]])


if __name__ == "__main__":
    unittest.main()
