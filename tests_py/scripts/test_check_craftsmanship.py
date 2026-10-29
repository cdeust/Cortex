"""Tests for scripts/check_craftsmanship.py — the CLI orchestrator.

Git interaction is mocked throughout (``gate.craftsmanship_git._run_git``)
so these tests never depend on the real repository's history or network
access; the detectors themselves are covered by the sibling
``test_craftsmanship_*`` modules and are exercised here only through the
plumbing (file scanning, exit codes). The end-to-end behaviour tests
(a regression is refused; a moving ``main`` changes nothing) live in
``test_check_craftsmanship_exploits.py`` — real `git` against a throwaway
repo, no mocking, split out to stay under this module's own 300-line cap.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Import the shared support FIRST: it registers craftsmanship_rules (and
# its siblings) under their bare names in sys.modules before gate.py loads
# — gate.py's own `import craftsmanship_rules as rules` then reuses that
# single cached instance instead of executing a second, dataclass-
# incompatible copy (see _craftsmanship_support.py's docstring).
import tests_py.scripts._craftsmanship_support  # noqa: F401

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_spec = importlib.util.spec_from_file_location(
    "scripts.check_craftsmanship", _SCRIPTS / "check_craftsmanship.py"
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


class ScanFilesTests(unittest.TestCase):
    def test_missing_file_yields_nothing(self) -> None:
        self.assertEqual(gate.scan_files(["does/not/exist.py"]), set())

    def test_reads_and_scans_a_real_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "clean.py"
            target.write_text("x = 1\n")
            with mock.patch.object(gate, "REPO_ROOT", Path(tmp)):
                self.assertEqual(gate.scan_files(["clean.py"]), set())


class MainExitCodeTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            code = gate.main(argv)
        return code, buf.getvalue()

    def test_explicit_clean_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "clean.py"
            target.write_text("x = 1\n")
            with mock.patch.object(gate, "REPO_ROOT", Path(tmp)):
                code, out = self._run(
                    ["--baseline", str(Path(tmp) / "baseline.json"), "clean.py"]
                )
            self.assertEqual(code, 0)
            self.assertIn("OK", out)

    def test_explicit_dirty_file_fails_with_no_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dirty.py"
            target.write_text("SENTINEL = 37\n")
            with mock.patch.object(gate, "REPO_ROOT", Path(tmp)):
                code, out = self._run(
                    ["--baseline", str(Path(tmp) / "baseline.json"), "dirty.py"]
                )
            self.assertEqual(code, 1)
            self.assertIn("SENTINEL", out)

    def test_baselined_violation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dirty.py"
            target.write_text("SENTINEL = 37\n")
            baseline_path = Path(tmp) / "baseline.json"
            gate.baseline_mod.save_baseline(
                baseline_path,
                {gate.rules.Violation("dirty.py", "unsourced-constant", "SENTINEL")},
            )
            with mock.patch.object(gate, "REPO_ROOT", Path(tmp)):
                code, out = self._run(["--baseline", str(baseline_path), "dirty.py"])
            self.assertEqual(code, 0)
            self.assertIn("OK", out)

    def test_no_files_measures_every_tracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dirty.py").write_text("SENTINEL = 37\n")
            with (
                mock.patch.object(gate, "REPO_ROOT", Path(tmp)),
                mock.patch.object(
                    gate.craftsmanship_git,
                    "all_tracked_python_files",
                    return_value=["dirty.py"],
                ),
                mock.patch.object(
                    gate.craftsmanship_decisions, "check_decisions", return_value=[]
                ),
            ):
                code, out = self._run(["--baseline", str(Path(tmp) / "baseline.json")])
            self.assertEqual(code, 1)
            self.assertIn("SENTINEL", out)

    def test_base_option_no_longer_exists(self) -> None:
        with self.assertRaises(SystemExit):
            self._run(["--base", "origin/main"])

    def test_write_baseline_regenerates_from_tracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "baseline.json"
            with (
                mock.patch.object(gate, "REPO_ROOT", Path(tmp)),
                mock.patch.object(
                    gate.craftsmanship_git, "all_tracked_python_files", return_value=[]
                ),
            ):
                code, out = self._run(
                    ["--write-baseline", "--baseline", str(baseline_path)]
                )
            self.assertEqual(code, 0)
            self.assertTrue(baseline_path.exists())


if __name__ == "__main__":
    unittest.main()
