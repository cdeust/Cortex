"""Tests for scripts/verify_sqlite_extra_parity.py — the real-install-path
[sqlite] extra guard (issue #636's Windows CI follow-up, generalizing
issue #634's root cause).

Mirrors tests_py/scripts/test_check_venv_lock_parity.py's structure: pure
parsing (`sqlite_extra_names`), the deps-dir comparison
(`missing_from_deps_dir`), and the CLI seam (`main`).
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]

# Dotted to match the path-derived name mutmut keys mutant trampolines on
# ("scripts.verify_sqlite_extra_parity.*") — a bare module name makes every
# mutant look unreached to a scoped mutation run (issue #262).
_spec = importlib.util.spec_from_file_location(
    "scripts.verify_sqlite_extra_parity",
    REPO / "scripts" / "verify_sqlite_extra_parity.py",
)
parity = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = parity
_spec.loader.exec_module(parity)


class SqliteExtraNamesTests(unittest.TestCase):
    def test_parses_a_simple_extra(self) -> None:
        text = '[project.optional-dependencies]\nsqlite = ["sqlite-vec>=0.1.1"]\n'
        self.assertEqual(parity.sqlite_extra_names(text), ["sqlite-vec"])

    def test_strips_version_specifiers_and_markers(self) -> None:
        text = (
            "[project.optional-dependencies]\n"
            "sqlite = [\"sqlite-vec>=0.1.1,<0.2 ; python_version >= '3.10'\"]\n"
        )
        self.assertEqual(parity.sqlite_extra_names(text), ["sqlite-vec"])

    def test_multiple_entries_preserve_declared_order(self) -> None:
        text = (
            "[project.optional-dependencies]\n"
            'sqlite = ["sqlite-vec>=0.1.1", "another-pkg==1.0"]\n'
        )
        self.assertEqual(parity.sqlite_extra_names(text), ["sqlite-vec", "another-pkg"])

    def test_real_pyproject_toml_declares_sqlite_vec(self) -> None:
        """Guard the parser against the real file: a silently-empty parse
        (wrong section name, changed TOML shape) would make every check
        below vacuously pass regardless of what BASE_PACKAGES installs."""
        names = parity.sqlite_extra_names(
            parity.PYPROJECT_TOML.read_text(encoding="utf-8")
        )
        self.assertIn("sqlite-vec", names)


class MissingFromDepsDirTests(unittest.TestCase):
    def _deps_dir_with(self, *entries: tuple[str, str]) -> Path:
        """``entries`` is ``(dist_info_dir_name, metadata_name_field)``
        pairs -- kept distinct because real wheels name the dist-info
        directory with underscores while METADATA's own ``Name:`` field
        can carry the package's original hyphenation."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        deps_dir = Path(tmp.name)
        for dist_info_dir, metadata_name in entries:
            d = deps_dir / dist_info_dir
            d.mkdir()
            (d / "METADATA").write_text(
                f"Metadata-Version: 2.1\nName: {metadata_name}\nVersion: 0.0.0\n",
                encoding="utf-8",
            )
        return deps_dir

    def test_nothing_missing_when_every_extra_name_is_installed(self) -> None:
        deps_dir = self._deps_dir_with(("sqlite_vec-0.1.9.dist-info", "sqlite-vec"))
        self.assertEqual(parity.missing_from_deps_dir(["sqlite-vec"], deps_dir), [])

    def test_reports_a_genuinely_missing_package(self) -> None:
        deps_dir = self._deps_dir_with()
        self.assertEqual(
            parity.missing_from_deps_dir(["sqlite-vec"], deps_dir), ["sqlite-vec"]
        )

    def test_normalizes_hyphen_underscore_like_pep_503(self) -> None:
        """The extra declares 'sqlite_vec' (underscore); the real wheel's
        dist-info directory is underscore-named but its own METADATA
        ``Name:`` field carries the hyphenated form, exactly like the real
        sqlite-vec wheel — must still match via PEP 503 normalization, not
        a literal string comparison."""
        deps_dir = self._deps_dir_with(("sqlite_vec-0.1.9.dist-info", "sqlite-vec"))
        self.assertEqual(parity.missing_from_deps_dir(["sqlite_vec"], deps_dir), [])

    def test_nonexistent_deps_dir_reports_every_name_missing(self) -> None:
        missing = parity.missing_from_deps_dir(
            ["sqlite-vec", "another-pkg"], Path("/no/such/deps/dir/at/all")
        )
        self.assertEqual(missing, ["another-pkg", "sqlite-vec"])

    def test_results_are_sorted(self) -> None:
        deps_dir = self._deps_dir_with()
        missing = parity.missing_from_deps_dir(["zzz-pkg", "aaa-pkg"], deps_dir)
        self.assertEqual(missing, ["aaa-pkg", "zzz-pkg"])


class MainCliTests(unittest.TestCase):
    def test_wrong_argv_count_returns_2(self) -> None:
        with mock.patch("builtins.print"):
            self.assertEqual(parity.main([]), 2)
            self.assertEqual(parity.main(["a", "b"]), 2)

    def test_returns_0_and_prints_ok_when_nothing_missing(self) -> None:
        with (
            mock.patch.object(parity, "sqlite_extra_names", return_value=["x"]),
            mock.patch.object(parity, "missing_from_deps_dir", return_value=[]),
            mock.patch("builtins.print") as mock_print,
        ):
            self.assertEqual(parity.main(["/some/deps"]), 0)
        mock_print.assert_called_once()
        self.assertIn("OK", mock_print.call_args.args[0])

    def test_returns_1_and_prints_the_missing_names_to_stderr(self) -> None:
        with (
            mock.patch.object(parity, "sqlite_extra_names", return_value=["x"]),
            mock.patch.object(
                parity, "missing_from_deps_dir", return_value=["sqlite-vec"]
            ),
            mock.patch("builtins.print") as mock_print,
        ):
            self.assertEqual(parity.main(["/some/deps"]), 1)
        mock_print.assert_called_once()
        args, kwargs = mock_print.call_args
        self.assertIn("sqlite-vec", args[0])
        self.assertEqual(kwargs.get("file"), sys.stderr)


if __name__ == "__main__":
    unittest.main()
