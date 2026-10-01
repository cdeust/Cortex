"""Tests for scripts/check_venv_lock_parity.py — the venv/CI collect-count
parity guard (issue #287).

Pins two things: the pure parsing/comparison logic (`parse_pinned_versions`,
`find_mismatches`), and the composed `postgresql_extra_drift` seam via a
monkeypatched `installed_version` — the same seam
`tests_py/conftest.py::_guard_against_venv_lock_drift` calls for real. A
final test reads `tests_py/conftest.py`'s own source to pin that the eager
call is still wired in, mirroring `test_typecheck_env_parity.py`'s pattern
of asserting documentation/CI text directly rather than trusting a human to
keep two files in sync.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]

# Dotted to match the path-derived name mutmut keys mutant trampolines on
# ("scripts.check_venv_lock_parity.*") — a bare module name makes every
# mutant look unreached to a scoped mutation run (issue #262).
_spec = importlib.util.spec_from_file_location(
    "scripts.check_venv_lock_parity", REPO / "scripts" / "check_venv_lock_parity.py"
)
parity = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = parity
_spec.loader.exec_module(parity)


class ParsePinnedVersionsTests(unittest.TestCase):
    def test_parses_a_simple_pinned_line(self) -> None:
        versions = parity.parse_pinned_versions("pgvector==0.5.0\n")
        self.assertEqual(versions, {"pgvector": "0.5.0"})

    def test_skips_comments_hashes_continuations_and_blanks(self) -> None:
        text = (
            "# a header comment\n"
            "\n"
            "psycopg==3.3.4 \\\n"
            "    --hash=sha256:deadbeef \\\n"
            "    # via some-consumer\n"
        )
        versions = parity.parse_pinned_versions(text)
        self.assertEqual(versions, {"psycopg": "3.3.4"})

    def test_marker_gated_line_included_when_marker_true(self) -> None:
        text = "foo==1.0.0 ; python_version >= '3.0'\n"
        self.assertEqual(parity.parse_pinned_versions(text), {"foo": "1.0.0"})

    def test_marker_gated_line_excluded_when_marker_false(self) -> None:
        text = "foo==1.0.0 ; python_version < '3.0'\n"
        self.assertEqual(parity.parse_pinned_versions(text), {})

    def test_python_version_fork_keeps_only_the_matching_branch(self) -> None:
        """The real file forks e.g. aiofile on python_full_version; only the
        branch matching THIS interpreter should survive, never both."""
        text = (
            "aiofile==3.9.0 ; python_full_version < '3.0'\n"
            "aiofile==3.11.1 ; python_full_version >= '3.0'\n"
        )
        self.assertEqual(parity.parse_pinned_versions(text), {"aiofile": "3.11.1"})

    def test_normalizes_underscores_and_case_like_pep_503(self) -> None:
        versions = parity.parse_pinned_versions("Psycopg_Pool==3.3.1\n")
        self.assertEqual(versions, {"psycopg-pool": "3.3.1"})

    def test_a_non_matching_line_is_skipped_not_fatal_to_the_rest(self) -> None:
        """A line that reaches the regex but fails it must `continue` to the
        next line, never `break` the whole loop — otherwise one malformed
        line anywhere in the file would silently truncate every package
        after it."""
        text = "not-a-pinned-requirement-line\npgvector==0.5.0\n"
        self.assertEqual(parity.parse_pinned_versions(text), {"pgvector": "0.5.0"})


class FindMismatchesTests(unittest.TestCase):
    def test_no_mismatch_when_versions_agree(self) -> None:
        pinned = {"pgvector": "0.5.0"}
        self.assertEqual(parity.find_mismatches(pinned, lambda _name: "0.5.0"), [])

    def test_mismatch_reports_installed_and_pinned_versions(self) -> None:
        pinned = {"pgvector": "0.5.0"}
        mismatches = parity.find_mismatches(pinned, lambda _name: "0.4.2")
        self.assertEqual(mismatches, ["pgvector: installed 0.4.2, lock pins 0.5.0"])

    def test_absent_package_is_not_a_mismatch(self) -> None:
        pinned = {"sqlite-vec": "0.1.9"}
        self.assertEqual(parity.find_mismatches(pinned, lambda _name: None), [])

    def test_mismatches_are_sorted_by_name(self) -> None:
        pinned = {"zzz-pkg": "1.0", "aaa-pkg": "2.0"}
        mismatches = parity.find_mismatches(pinned, lambda _name: "0.0")
        self.assertEqual(
            mismatches,
            [
                "aaa-pkg: installed 0.0, lock pins 2.0",
                "zzz-pkg: installed 0.0, lock pins 1.0",
            ],
        )


class InstalledVersionTests(unittest.TestCase):
    def test_returns_none_for_an_uninstalled_distribution(self) -> None:
        self.assertIsNone(parity.installed_version("definitely-not-a-real-package-xyz"))

    def test_returns_the_real_version_for_an_installed_distribution(self) -> None:
        # pytest itself is always installed in a test-running environment.
        self.assertEqual(
            parity.installed_version("pytest"), importlib.metadata.version("pytest")
        )


class PostgresqlExtraDriftTests(unittest.TestCase):
    """`postgresql_extra_drift` composed end-to-end, with `installed_version`
    monkeypatched so the test is deterministic regardless of THIS machine's
    actual venv state (issue #287 is precisely about that state varying)."""

    def test_none_when_psycopg_is_not_installed(self) -> None:
        with mock.patch.object(parity, "installed_version", return_value=None):
            self.assertIsNone(parity.postgresql_extra_drift())

    def test_none_when_installed_matches_the_pinned_file(self) -> None:
        locked = "psycopg==3.3.4\npgvector==0.5.0\n"
        versions = {"psycopg": "3.3.4", "pgvector": "0.5.0"}
        with (
            mock.patch.object(parity, "locked_requirements", return_value=locked),
            mock.patch.object(parity, "installed_version", side_effect=versions.get),
        ):
            self.assertIsNone(parity.postgresql_extra_drift())

    def test_reports_the_exact_drift_that_caused_issue_287(self) -> None:
        """psycopg importable, pgvector present but at the pre-drift version
        — the concrete pair measured the day before this issue was filed.
        Exact equality (not `assertIn`): a
        wording tweak to any chunk of the message is a real change a
        reviewer should see reflected here, not something a substring check
        would silently keep passing under."""
        locked = "psycopg==3.3.4\npgvector==0.5.0\n"
        versions = {"psycopg": "3.3.4", "pgvector": "0.4.2"}
        with (
            mock.patch.object(parity, "locked_requirements", return_value=locked),
            mock.patch.object(parity, "installed_version", side_effect=versions.get),
        ):
            message = parity.postgresql_extra_drift()
        self.assertEqual(
            message,
            "Local venv has drifted from uv.lock's dev+postgresql+codebase set — "
            "the set CI's 'Check advertised test count' step installs "
            "(issue #287). A version-mismatched postgresql-extra package can "
            "change which tests import successfully at collection time, so "
            "the locally collected test count silently stops matching CI's. "
            "Mismatches:\n"
            "  pgvector: installed 0.4.2, lock pins 0.5.0\n"
            "Fix: re-run `uv sync --no-default-groups --extra dev --extra "
            "postgresql --extra sqlite --extra codebase --extra benchmarks` "
            "(CONTRIBUTING.md § Dev setup) to resync this venv to uv.lock.",
        )

    def test_multiple_mismatches_are_newline_joined(self) -> None:
        """A single-mismatch message can't distinguish the join separator
        from a corrupted one — both produce the same one-line output. Two+
        mismatches are required to pin that each gets its own line."""
        locked = "psycopg==3.3.4\npgvector==0.5.0\npsycopg-pool==3.3.1\n"
        versions = {
            "psycopg": "3.3.4",
            "pgvector": "0.4.2",
            "psycopg-pool": "3.3.0",
        }
        with (
            mock.patch.object(parity, "locked_requirements", return_value=locked),
            mock.patch.object(parity, "installed_version", side_effect=versions.get),
        ):
            message = parity.postgresql_extra_drift()
        assert message is not None
        mismatch_block = message.split("Mismatches:\n", 1)[1].split("\nFix:", 1)[0]
        self.assertEqual(
            mismatch_block,
            "  pgvector: installed 0.4.2, lock pins 0.5.0\n"
            "  psycopg-pool: installed 3.3.0, lock pins 3.3.1",
        )

    def test_unreadable_lock_is_reported_not_passed(self) -> None:
        unreadable = parity.LockUnreadableError("uv is not on PATH")
        with (
            mock.patch.object(parity, "installed_version", return_value="3.3.4"),
            mock.patch.object(parity, "locked_requirements", side_effect=unreadable),
        ):
            message = parity.postgresql_extra_drift()
        self.assertEqual(
            message, "Cannot read uv.lock's pins to check this venv: uv is not on PATH"
        )

    def test_real_lock_export_parses_to_a_realistic_package_set(self) -> None:
        """Guard the parser against the real export: a silently-empty parse
        would make every reconciliation above vacuously pass."""
        versions = parity.parse_pinned_versions(parity.locked_requirements())
        # dev+postgresql+codebase is ~90 packages; 50 is far above empty.
        self.assertGreater(len(versions), 50)
        self.assertIn("psycopg", versions)
        self.assertIn("pgvector", versions)


class LockedRequirementsTests(unittest.TestCase):
    def test_exports_the_ci_set_from_the_lock_without_hashes(self) -> None:
        done = mock.Mock(returncode=0, stdout="x==1\n", stderr="")
        with (
            mock.patch.object(parity.shutil, "which", return_value="/bin/uv"),
            mock.patch.object(parity.subprocess, "run", return_value=done) as run,
        ):
            self.assertEqual(parity.locked_requirements(), "x==1\n")
        self.assertEqual(
            run.call_args.args[0],
            ["/bin/uv", "export", "--frozen", "--no-config", "--project"]
            + [str(REPO), "--no-emit-project", "--no-default-groups"]
            + ["--extra", "dev", "--extra", "postgresql", "--extra", "codebase"]
            + ["--format", "requirements.txt", "--no-hashes"],
        )

    def test_missing_uv_or_failed_export_raises(self) -> None:
        with mock.patch.object(parity.shutil, "which", return_value=None):
            with self.assertRaises(parity.LockUnreadableError):
                parity.locked_requirements()
        failed = mock.Mock(returncode=2, stdout="", stderr="lock is stale")
        with (
            mock.patch.object(parity.shutil, "which", return_value="/bin/uv"),
            mock.patch.object(parity.subprocess, "run", return_value=failed),
        ):
            with self.assertRaisesRegex(parity.LockUnreadableError, "lock is stale"):
                parity.locked_requirements()


class MainCliTests(unittest.TestCase):
    def test_main_prints_ok_and_returns_0_when_no_drift(self) -> None:
        with (
            mock.patch.object(parity, "postgresql_extra_drift", return_value=None),
            mock.patch("builtins.print") as mock_print,
        ):
            self.assertEqual(parity.main([]), 0)
        mock_print.assert_called_once_with(
            "OK: no postgresql-extra version drift from uv.lock"
        )

    def test_main_prints_the_message_and_returns_1_on_drift(self) -> None:
        with (
            mock.patch.object(
                parity, "postgresql_extra_drift", return_value="drifted: x"
            ),
            mock.patch("builtins.print") as mock_print,
        ):
            self.assertEqual(parity.main([]), 1)
        mock_print.assert_called_once_with("drifted: x", file=sys.stderr)


class ConftestWiringTests(unittest.TestCase):
    """Pin that tests_py/conftest.py still calls the guard eagerly — a
    future edit that imports the module but drops the call site would leave
    the check dead code that never runs."""

    def test_conftest_imports_and_calls_the_guard(self) -> None:
        conftest = (REPO / "tests_py" / "conftest.py").read_text(encoding="utf-8")
        self.assertIn(
            "from scripts.check_venv_lock_parity import postgresql_extra_drift",
            conftest,
        )
        self.assertIn("_guard_against_venv_lock_drift()", conftest)


if __name__ == "__main__":
    unittest.main()
