"""Tests for scripts/craftsmanship_constants.py — rule 4 (unsourced
module-scope numeric literals).
"""

from __future__ import annotations

import ast
import unittest

from tests_py.scripts._craftsmanship_support import (
    craftsmanship_constants as constants_mod,
)


def _find(source: str):
    tree = ast.parse(source)
    return constants_mod.check_unsourced_constants("f.py", tree, source)


class UnsourcedConstantTests(unittest.TestCase):
    def test_unsourced_constant_fails(self) -> None:
        violations = _find("TIMEOUT_SECONDS = 37\n")
        self.assertEqual([v.detail for v in violations], ["TIMEOUT_SECONDS"])

    def test_preceding_source_comment_passes(self) -> None:
        source = (
            "# source: measured 2026-08-10, benchmarks/x.json\nTIMEOUT_SECONDS = 37\n"
        )
        self.assertEqual(_find(source), [])

    def test_trailing_inline_source_comment_passes(self) -> None:
        source = "TIMEOUT_SECONDS = 37  # source: RFC 9110 timeout guidance\n"
        self.assertEqual(_find(source), [])

    def test_blank_line_breaks_the_comment_chain(self) -> None:
        source = "# source: measured\n\nTIMEOUT_SECONDS = 37\n"
        violations = _find(source)
        self.assertEqual([v.detail for v in violations], ["TIMEOUT_SECONDS"])

    def test_annassign_target_is_checked(self) -> None:
        violations = _find("TIMEOUT_SECONDS: int = 37\n")
        self.assertEqual([v.detail for v in violations], ["TIMEOUT_SECONDS"])

    def test_negative_one_is_trivial(self) -> None:
        self.assertEqual(_find("SENTINEL = -1\n"), [])

    def test_zero_one_two_hundred_thousand_are_trivial(self) -> None:
        source = "A = 0\nB = 1\nC = 2\nD = 100\nE = 1000\n"
        self.assertEqual(_find(source), [])

    def test_usual_power_of_two_is_trivial(self) -> None:
        self.assertEqual(_find("BUFFER_SIZE = 4096\n"), [])

    def test_non_trivial_negative_number_still_needs_a_source(self) -> None:
        violations = _find("OFFSET = -37\n")
        self.assertEqual([v.detail for v in violations], ["OFFSET"])

    def test_function_local_constant_is_not_checked(self) -> None:
        source = "def f():\n    TIMEOUT_SECONDS = 37\n    return TIMEOUT_SECONDS\n"
        self.assertEqual(_find(source), [])

    def test_string_constant_is_not_checked(self) -> None:
        self.assertEqual(_find('GREETING = "hello"\n'), [])

    def test_bool_constant_is_not_checked(self) -> None:
        self.assertEqual(_find("ENABLED = True\n"), [])


if __name__ == "__main__":
    unittest.main()
