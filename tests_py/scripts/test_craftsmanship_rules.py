"""Tests for scripts/craftsmanship_rules.py — rules 1-2 (file/method size)
plus the ``scan_source`` aggregator.

Boundary cases pinned explicitly (task acceptance criteria): a file at
exactly the 300-line cap passes, one line over fails; a decorated, a
nested, and an ``async def`` method are all measured correctly; an
auto-generated file is exempt from the file-size rule.
"""

from __future__ import annotations

import unittest

from tests_py.scripts._craftsmanship_support import rules


def _lines(n: int) -> str:
    """A syntactically valid module body of exactly n lines."""
    return "\n".join(f"x{i} = {i}" for i in range(n))


class FileSizeTests(unittest.TestCase):
    def test_exactly_at_cap_passes(self) -> None:
        source = _lines(rules.FILE_LINE_LIMIT)
        self.assertEqual(rules.check_file_size("f.py", source), [])

    def test_one_over_cap_fails(self) -> None:
        source = _lines(rules.FILE_LINE_LIMIT + 1)
        violations = rules.check_file_size("f.py", source)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].kind, "file-size")

    def test_auto_generated_file_is_exempt(self) -> None:
        source = "# auto-generated, do not edit\n" + _lines(rules.FILE_LINE_LIMIT + 50)
        self.assertEqual(rules.check_file_size("f.py", source), [])

    def test_auto_generated_marker_case_insensitive(self) -> None:
        source = "# Auto-Generated\n" + _lines(rules.FILE_LINE_LIMIT + 1)
        self.assertEqual(rules.check_file_size("f.py", source), [])


class MethodSizeTests(unittest.TestCase):
    def _violations(self, source: str) -> list:
        import ast

        tree = ast.parse(source)
        return rules.check_method_size("f.py", tree)

    def test_short_function_passes(self) -> None:
        source = "def f():\n" + "\n".join("    pass" for _ in range(5))
        self.assertEqual(self._violations(source), [])

    def test_long_function_fails(self) -> None:
        body = "\n".join("    x = 1" for _ in range(rules.METHOD_LINE_LIMIT + 5))
        source = f"def f():\n{body}"
        violations = self._violations(source)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].detail, "f")

    def test_decorated_method_measured_by_body_not_decorator(self) -> None:
        body = "\n".join("        x = 1" for _ in range(10))
        source = f"class C:\n    @staticmethod\n    def m():\n{body}"
        self.assertEqual(self._violations(source), [])

    def test_nested_function_gets_dotted_qualified_name(self) -> None:
        # `inner`'s oversized body is lexically part of `outer` too, so
        # both are legitimately over the cap — this pins the qualified
        # name, not the count.
        body = "\n".join("        y = 1" for _ in range(rules.METHOD_LINE_LIMIT + 3))
        source = f"def outer():\n    def inner():\n{body}\n    return inner"
        violations = self._violations(source)
        names = sorted(v.detail for v in violations)
        self.assertIn("outer.inner", names)

    def test_async_method_in_class_gets_qualified_name(self) -> None:
        body = "\n".join("        x = 1" for _ in range(rules.METHOD_LINE_LIMIT + 3))
        source = f"class C:\n    async def m(self):\n{body}"
        violations = self._violations(source)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].detail, "C.m")


class ScanSourceTests(unittest.TestCase):
    def test_syntax_error_returns_empty_not_raises(self) -> None:
        self.assertEqual(rules.scan_source("f.py", "def f(:\n"), [])

    def test_clean_source_has_no_violations(self) -> None:
        self.assertEqual(rules.scan_source("f.py", "x = 1\n"), [])


if __name__ == "__main__":
    unittest.main()
