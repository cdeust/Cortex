"""CI environment checks must preserve the supported installation contract.

Source: ADR-1114, and PR792's missing drivers/database with unbounded Python.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location(
        "ci_environment_setup", SCRIPTS / "ci_environment.py"
    )
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
finally:
    sys.path.remove(str(SCRIPTS))


class EnvironmentSetup(unittest.TestCase):
    def test_isolation_does_not_inherit_a_live_database_or_python_environment(self):
        inherited = {
            "PATH": "/system/bin",
            "SystemRoot": "C:/Windows",
            "USERNAME": "runneradmin",
            "USERDOMAIN": "BUILDHOST",
            "GH_TOKEN": "must-not-be-inherited",
            "DATABASE_URL": "postgresql://production/store",
            "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
            "PYTHONPATH": "/another/runtime",
            "PGSERVICE": "production",
        }
        work = Path("/private/probe")
        result = setup.isolated_environment(work, inherited)
        for forbidden in (
            "DATABASE_URL",
            "CORTEX_MEMORY_STORE_BACKEND",
            "PYTHONPATH",
            "PGSERVICE",
            "GH_TOKEN",
        ):
            self.assertNotIn(forbidden, result)
        self.assertEqual(result["SystemRoot"], "C:/Windows")
        self.assertEqual(result["USERNAME"], "runneradmin")
        self.assertEqual(result["USERDOMAIN"], "BUILDHOST")
        self.assertEqual(result["CORTEX_CLAUDE_DIR"], str(work / "home/.claude"))
        self.assertEqual(result["HOME"], result["USERPROFILE"])

    def test_windows_runs_the_powershell_hook_contract_and_propagates_failure(self):
        with (
            patch.object(setup.os, "name", "nt"),
            patch.object(
                setup.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "pwsh"),
            ) as run,
            self.assertRaises(subprocess.CalledProcessError),
        ):
            setup.check_windows_bash_contract()
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "pwsh")
        self.assertIn(str(SCRIPTS / "ci_windows_bash.ps1"), argv)
        self.assertIn(sys.executable, argv)
        self.assertEqual(run.call_args.kwargs["cwd"], SCRIPTS.parent)
        self.assertTrue(run.call_args.kwargs["check"])

    def test_other_hosts_do_not_run_the_powershell_probe(self):
        with patch.object(setup.os, "name", "posix"), patch.object(
            setup.subprocess, "run"
        ) as run:
            setup.check_windows_bash_contract()
        run.assert_not_called()

    def test_existing_work_directory_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            sentinel = work / "keep"
            sentinel.write_text("owned elsewhere")
            with self.assertRaises(FileExistsError):
                setup.run_isolated(work)
            self.assertEqual(sentinel.read_text(), "owned elsewhere")

    def test_bootstrap_failure_is_the_environment_command_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "probe"
            with patch.object(
                setup.subprocess, "run", return_value=SimpleNamespace(returncode=17)
            ) as run:
                self.assertEqual(setup.run_isolated(work), 17)
            self.assertEqual(run.call_args.kwargs["cwd"], work)
            self.assertEqual(run.call_args.kwargs["env"]["HOME"], str(work / "home"))

    def test_supported_host_requires_managed_postgresql(self):
        setup.require_backend(
            SimpleNamespace(failed="", fallback=""),
            {"backend": "managed"},
            windows=False,
        )
        for fallback, marker in (
            ("download checksum mismatch", {"backend": "sqlite"}),
            ("", {"backend": "sqlite"}),
            ("", None),
        ):
            with (
                self.subTest(fallback=fallback, marker=marker),
                self.assertRaises(RuntimeError),
            ):
                setup.require_backend(
                    SimpleNamespace(failed="", fallback=fallback), marker, windows=False
                )

    def test_windows_requires_visible_unsupported_host_and_real_sqlite_selection(self):
        outcome = SimpleNamespace(
            failed="", fallback="managed PostgreSQL unavailable here (Windows)"
        )
        setup.require_backend(outcome, {"backend": "sqlite"}, windows=True)
        for fallback, marker in (
            ("", {"backend": "sqlite"}),
            (
                "managed PostgreSQL did not start: checksum failure",
                {"backend": "sqlite"},
            ),
            (outcome.fallback, None),
            (outcome.fallback, {"backend": "managed"}),
        ):
            with (
                self.subTest(fallback=fallback, marker=marker),
                self.assertRaises(RuntimeError),
            ):
                setup.require_backend(
                    SimpleNamespace(failed="", fallback=fallback), marker, windows=True
                )

    def test_previously_managed_store_failure_is_fatal_on_every_host(self):
        for windows in (False, True):
            with (
                self.subTest(windows=windows),
                self.assertRaisesRegex(RuntimeError, "broken cluster"),
            ):
                setup.require_backend(
                    SimpleNamespace(failed="broken cluster", fallback=""),
                    {"backend": "managed"},
                    windows=windows,
                )


if __name__ == "__main__":
    unittest.main()
