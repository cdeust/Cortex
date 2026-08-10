"""Tests for scripts/check_craftsmanship.py — the CLI orchestrator.

Git interaction is mocked throughout (``gate.craftsmanship_git._run_git``)
so these tests never depend on the real repository's history or network
access; the detectors themselves are covered by the sibling
``test_craftsmanship_*`` modules and are exercised here only through the
plumbing (file scanning, base-ref resolution, exit codes). The two
end-to-end exploit reproductions
(``test_check_craftsmanship_exploits.py::SneakyLimitExploitTests``,
``FalsifiedRemovalExploitTests``) live in their own file — real `git`
against a throwaway repo, no mocking, split out to stay under this
module's own 300-line cap.
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


class ResolveBaseRefTests(unittest.TestCase):
    def test_explicit_ref_wins_when_it_exists(self) -> None:
        with mock.patch.object(gate.craftsmanship_git, "_run_git", return_value="ok"):
            self.assertEqual(
                gate.craftsmanship_git.resolve_base_ref(gate.REPO_ROOT, "mybranch"),
                "mybranch",
            )

    def test_falls_back_to_origin_main(self) -> None:
        def fake(repo_root: Path, args: list[str]):
            return "ok" if args == ["rev-parse", "--verify", "origin/main"] else None

        with mock.patch.object(gate.craftsmanship_git, "_run_git", side_effect=fake):
            self.assertEqual(
                gate.craftsmanship_git.resolve_base_ref(gate.REPO_ROOT, None),
                "origin/main",
            )

    def test_none_when_nothing_resolves(self) -> None:
        with mock.patch.object(gate.craftsmanship_git, "_run_git", return_value=None):
            self.assertIsNone(
                gate.craftsmanship_git.resolve_base_ref(gate.REPO_ROOT, None)
            )


class ChangedPythonFilesTests(unittest.TestCase):
    def test_filters_blank_lines_and_sorts(self) -> None:
        with mock.patch.object(
            gate.craftsmanship_git, "_run_git", return_value="b.py\n\na.py\n"
        ):
            self.assertEqual(
                gate.craftsmanship_git.changed_python_files(
                    gate.REPO_ROOT, "origin/main"
                ),
                ["a.py", "b.py"],
            )

    def test_none_when_git_diff_fails(self) -> None:
        with mock.patch.object(gate.craftsmanship_git, "_run_git", return_value=None):
            self.assertIsNone(
                gate.craftsmanship_git.changed_python_files(
                    gate.REPO_ROOT, "origin/main"
                )
            )


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

    def test_no_base_ref_and_no_files_exits_two(self) -> None:
        with mock.patch.object(
            gate.craftsmanship_git, "resolve_base_ref", return_value=None
        ):
            code, out = self._run([])
            self.assertEqual(code, 2)

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


class GitPathExistsAtRefTests(unittest.TestCase):
    """Self-audited third instance of the "ambiguous failure read as a
    negative" pattern the review round's other two findings shared: a bare
    ``except: return False`` here would let ANY git failure — not just a
    genuinely absent path — silently trigger ``load_baseline_from_ref``'s
    bootstrap fallback to the tamperable working-tree baseline.
    """

    def test_real_absent_path_returns_false(self) -> None:
        # Live integration: a path that has never existed at a real,
        # resolvable ref in THIS repository.
        result = gate.craftsmanship_git._git_path_exists_at_ref(
            gate.REPO_ROOT, "HEAD", "this/path/has/never/existed.json"
        )
        self.assertFalse(result)

    def test_real_existing_path_returns_true(self) -> None:
        result = gate.craftsmanship_git._git_path_exists_at_ref(
            gate.REPO_ROOT, "HEAD", "CLAUDE.md"
        )
        self.assertTrue(result)

    def test_invalid_ref_raises_not_returns_false(self) -> None:
        # A ref that does not resolve at all must never be silently read
        # as "the path just doesn't exist yet" — resolve_base_ref should
        # already have filtered this out, but this function must not
        # compound a caller's bug into a security-relevant fail-open.
        with self.assertRaises(RuntimeError):
            gate.craftsmanship_git._git_path_exists_at_ref(
                gate.REPO_ROOT, "totally-bogus-ref-xyz", "CLAUDE.md"
            )

    def test_unexpected_git_failure_raises(self) -> None:
        fake_result = mock.Mock(returncode=128, stderr="fatal: something unexpected")
        with mock.patch("subprocess.run", return_value=fake_result):
            with self.assertRaises(RuntimeError):
                gate.craftsmanship_git._git_path_exists_at_ref(
                    gate.REPO_ROOT, "main", "x.json"
                )


class LoadBaselineFromRefTests(unittest.TestCase):
    """Unit-level coverage of the git-show-based base-ref loader; the
    end-to-end exploit reproductions live in test_check_craftsmanship_exploits.py.
    """

    def test_none_ref_gives_none(self) -> None:
        self.assertIsNone(
            gate.craftsmanship_git.load_baseline_from_ref(
                gate.REPO_ROOT, None, Path("/tmp/x.json")
            )
        )

    def test_path_outside_repo_gives_none(self) -> None:
        result = gate.craftsmanship_git.load_baseline_from_ref(
            Path("/repo"), "main", Path("/elsewhere/x.json")
        )
        self.assertIsNone(result)

    def test_path_absent_at_ref_gives_none_bootstrap(self) -> None:
        with mock.patch.object(
            gate.craftsmanship_git, "_git_path_exists_at_ref", return_value=False
        ):
            result = gate.craftsmanship_git.load_baseline_from_ref(
                gate.REPO_ROOT, "main", gate.REPO_ROOT / "x.json"
            )
        self.assertIsNone(result)

    def test_show_failure_after_confirmed_existence_raises(self) -> None:
        with (
            mock.patch.object(
                gate.craftsmanship_git, "_git_path_exists_at_ref", return_value=True
            ),
            mock.patch.object(gate.craftsmanship_git, "_run_git", return_value=None),
        ):
            with self.assertRaises(RuntimeError):
                gate.craftsmanship_git.load_baseline_from_ref(
                    gate.REPO_ROOT, "main", gate.REPO_ROOT / "x.json"
                )

    def test_parses_show_output(self) -> None:
        payload = (
            '{"violations": [{"file": "a.py", "kind": "file-size", "detail": "d"}]}'
        )
        with (
            mock.patch.object(
                gate.craftsmanship_git, "_git_path_exists_at_ref", return_value=True
            ),
            mock.patch.object(gate.craftsmanship_git, "_run_git", return_value=payload),
        ):
            result = gate.craftsmanship_git.load_baseline_from_ref(
                gate.REPO_ROOT, "main", gate.REPO_ROOT / "x.json"
            )
        self.assertEqual(result, {gate.rules.Violation("a.py", "file-size", "d")})


if __name__ == "__main__":
    unittest.main()
