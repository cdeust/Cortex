"""Tests for scripts/check_craftsmanship.py — the CLI orchestrator.

Git interaction is mocked throughout (``gate._run_git``) so these tests
never depend on the real repository's history or network access; the
detectors themselves are covered by the sibling ``test_craftsmanship_*``
modules and are exercised here only through the plumbing (file scanning,
base-ref resolution, exit codes).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
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
        with mock.patch.object(gate, "_run_git", return_value="ok"):
            self.assertEqual(gate.resolve_base_ref("mybranch"), "mybranch")

    def test_falls_back_to_origin_main(self) -> None:
        def fake(args: list[str]):
            return "ok" if args == ["rev-parse", "--verify", "origin/main"] else None

        with mock.patch.object(gate, "_run_git", side_effect=fake):
            self.assertEqual(gate.resolve_base_ref(None), "origin/main")

    def test_none_when_nothing_resolves(self) -> None:
        with mock.patch.object(gate, "_run_git", return_value=None):
            self.assertIsNone(gate.resolve_base_ref(None))


class ChangedPythonFilesTests(unittest.TestCase):
    def test_filters_blank_lines_and_sorts(self) -> None:
        with mock.patch.object(gate, "_run_git", return_value="b.py\n\na.py\n"):
            self.assertEqual(gate.changed_python_files("origin/main"), ["a.py", "b.py"])

    def test_none_when_git_diff_fails(self) -> None:
        with mock.patch.object(gate, "_run_git", return_value=None):
            self.assertIsNone(gate.changed_python_files("origin/main"))


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
        with mock.patch.object(gate, "resolve_base_ref", return_value=None):
            code, out = self._run([])
            self.assertEqual(code, 2)

    def test_write_baseline_regenerates_from_tracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "baseline.json"
            with (
                mock.patch.object(gate, "REPO_ROOT", Path(tmp)),
                mock.patch.object(gate, "all_tracked_python_files", return_value=[]),
            ):
                code, out = self._run(
                    ["--write-baseline", "--baseline", str(baseline_path)]
                )
            self.assertEqual(code, 0)
            self.assertTrue(baseline_path.exists())


class LoadBaselineFromRefTests(unittest.TestCase):
    """Unit-level coverage of the git-show-based base-ref loader; the
    end-to-end exploit reproduction lives in SneakyLimitExploitTests below.
    """

    def test_none_ref_gives_none(self) -> None:
        self.assertIsNone(gate.load_baseline_from_ref(None, Path("/tmp/x.json")))

    def test_path_outside_repo_gives_none(self) -> None:
        with mock.patch.object(gate, "REPO_ROOT", Path("/repo")):
            self.assertIsNone(
                gate.load_baseline_from_ref("main", Path("/elsewhere/x.json"))
            )

    def test_path_absent_at_ref_gives_none_bootstrap(self) -> None:
        with mock.patch.object(gate, "_git_path_exists_at_ref", return_value=False):
            result = gate.load_baseline_from_ref("main", gate.REPO_ROOT / "x.json")
        self.assertIsNone(result)

    def test_show_failure_after_confirmed_existence_raises(self) -> None:
        with (
            mock.patch.object(gate, "_git_path_exists_at_ref", return_value=True),
            mock.patch.object(gate, "_run_git", return_value=None),
        ):
            with self.assertRaises(RuntimeError):
                gate.load_baseline_from_ref("main", gate.REPO_ROOT / "x.json")

    def test_parses_show_output(self) -> None:
        payload = (
            '{"violations": [{"file": "a.py", "kind": "file-size", "detail": "d"}]}'
        )
        with (
            mock.patch.object(gate, "_git_path_exists_at_ref", return_value=True),
            mock.patch.object(gate, "_run_git", return_value=payload),
        ):
            result = gate.load_baseline_from_ref("main", gate.REPO_ROOT / "x.json")
        self.assertEqual(result, {gate.rules.Violation("a.py", "file-size", "d")})


class SneakyLimitExploitTests(unittest.TestCase):
    """Reproduces, against a real throwaway git repository, the exact
    review-round exploit and its close: a working-tree-only baseline can
    be self-regenerated (``--write-baseline`` in the same tree) to launder
    a violation the gate had just refused. Runs `git` for real — no
    mocking — because the exploit IS about what a real `git show` against
    an immutable base ref sees versus what the mutable working tree says.
    """

    def _git(self, repo: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        )

    def _init_repo(self, repo: Path) -> None:
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "scripts").mkdir()
        (repo / "docs").mkdir()
        (repo / "mcp_server" / "core").mkdir(parents=True)
        for name in (
            "craftsmanship_rules.py",
            "craftsmanship_imports.py",
            "craftsmanship_constants.py",
            "craftsmanship_baseline.py",
            "craftsmanship_layer_table.py",
            "check_craftsmanship.py",
        ):
            (repo / "scripts" / name).write_text((_SCRIPTS / name).read_text())
        (repo / "docs" / "module-inventory.md").write_text(
            (_SCRIPTS.parent / "docs" / "module-inventory.md").read_text()
        )
        # `-b main` pins the initial branch name explicitly: this repo's
        # own default is "main" locally, but git's `init.defaultBranch`
        # is a per-installation config (CI runners are not guaranteed to
        # match), and this test hardcodes "main" as the base ref below.
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "demo@example.com")
        self._git(repo, "config", "user.name", "demo")

    def _run_gate_in(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(repo / "scripts" / "check_craftsmanship.py"), *args],
            cwd=repo,
            capture_output=True,
            text=True,
        )

    def test_exploit_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_repo(repo)
            (repo / "mcp_server" / "core" / "sample.py").write_text("SAFE = 1\n")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-q", "-m", "main v1")
            self._run_gate_in(repo, "--write-baseline")
            self._git(repo, "add", ".craftsmanship-baseline.json")
            self._git(repo, "commit", "-q", "-m", "main v2: baseline committed")

            self._git(repo, "checkout", "-q", "-b", "feature")
            sample = repo / "mcp_server" / "core" / "sample.py"
            sample.write_text(sample.read_text() + "SNEAKY_LIMIT = 12345\n")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-q", "-m", "feature: sneaky const")

            # Step 1: the gate blocks the new violation.
            blocked = self._run_gate_in(repo, "--base", "main")
            self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)
            self.assertIn("SNEAKY_LIMIT", blocked.stdout + blocked.stderr)

            # Step 2: the attack — launder it via a same-tree regenerate.
            self._run_gate_in(repo, "--write-baseline")

            # Step 3: must STILL block — this is the exploit's close.
            after_attack = self._run_gate_in(repo, "--base", "main")
            self.assertEqual(
                after_attack.returncode, 1, after_attack.stdout + after_attack.stderr
            )
            self.assertIn("SNEAKY_LIMIT", after_attack.stdout + after_attack.stderr)
            self.assertIn("ADDED", after_attack.stdout + after_attack.stderr)

    def test_legitimate_shrink_only_baseline_update_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            self._init_repo(repo)
            stale_file = repo / "mcp_server" / "core" / "todelete.py"
            stale_file.write_text("STALE_ONE = 999999\n")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-q", "-m", "main v1: has a violation")
            self._run_gate_in(repo, "--write-baseline")
            self._git(repo, "add", ".craftsmanship-baseline.json")
            self._git(repo, "commit", "-q", "-m", "main v2: baseline committed")

            self._git(repo, "checkout", "-q", "-b", "fixer")
            stale_file.unlink()
            self._git(repo, "add", "-A")

            # Fixed the code but forgot to prune -> STALE, still blocks.
            forgot_prune = self._run_gate_in(repo, "--base", "main")
            self.assertEqual(forgot_prune.returncode, 1)
            self.assertIn("STALE", forgot_prune.stdout + forgot_prune.stderr)

            # Regenerating is a pure shrink (one entry removed, none
            # added) -> passes.
            self._run_gate_in(repo, "--write-baseline")
            self._git(repo, "add", "-A")
            clean = self._run_gate_in(repo, "--base", "main")
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)


if __name__ == "__main__":
    unittest.main()
