"""Runs the permanent no-comparison-against-main guard inside the pytest unit suite.

Owner rule 2026-10-29: no CI check may compare a pull request with main.
The scan itself lives in scripts/tests/test_no_main_comparison.py.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "tests" / "test_no_main_comparison.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("no_main_comparison_guard", GUARD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NoMainComparisonGuardTests(unittest.TestCase):
    def test_guard_script_passes(self) -> None:
        guard = _load_guard()
        self.assertEqual(guard.find_violations(ROOT), [])

    def test_guard_script_detects_every_marker(self) -> None:
        suite = unittest.defaultTestLoader.loadTestsFromName(
            "test_guard_detects_every_forbidden_marker", _load_guard().NoMainComparisonTests
        )
        result = unittest.TestResult()
        suite.run(result)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)


if __name__ == "__main__":
    unittest.main()
