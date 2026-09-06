"""CLI dispatch precedes all bootstrap and backend activity."""

from __future__ import annotations

import builtins
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tests_py.scripts._cleanup_fixture import HAS_SAFE_FS, SCRIPTS, CleanupFixture

import launcher_cleanup
import launcher


@unittest.skipUnless(HAS_SAFE_FS, "platform lacks no-follow descriptor operations")
class TestCleanupCli(CleanupFixture):
    def environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "CORTEX_CLAUDE_DIR": str(self.root),
            "CLAUDE_PLUGIN_DATA": str(self.scope.current_deps.parent),
            "CLAUDE_PLUGIN_ROOT": str(self.workspace / "missing-plugin"),
            "PYTHONPATH": "",
            "HOME": str(self.workspace / "unused-home"),
        }

    def run_cli(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-S", str(SCRIPTS / "launcher.py"), *arguments],
            env=self.environment(),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_dry_run_without_site_packages_does_not_bootstrap_or_run_module(
        self,
    ) -> None:
        before = self.all_deps()
        result = self.run_cli(
            ["--cleanup-deps", "--dry-run", "--plugin-id", "orphan@market"]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(len(report["candidates"]), 1)
        self.assertFalse(report["removed"])
        self.assertEqual(before, self.all_deps())
        self.assertFalse((self.workspace / "unused-home").exists())
        self.assertEqual(result.stderr, "")

    def test_malformed_flags_fail_before_bootstrap(self) -> None:
        for arguments in (
            ["--dry-run"],
            ["--apply"],
            ["--plugin-id", "orphan@market"],
            ["--cleanup-deps", "--dry-run", "--apply"],
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cli(arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("usage:", result.stderr)
                self.assertNotIn("backend", result.stderr)
                self.assertNotIn("Installing", result.stderr)

    def test_missing_explicit_environment_refuses_without_home_lookup(self) -> None:
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output):
            with self.assertLogs("launcher_cleanup", level="WARNING"):
                result = launcher_cleanup.cli(["--cleanup-deps", "--dry-run"])
        self.assertNotEqual(result, 0)
        self.assertIn("CORTEX_CLAUDE_DIR", json.loads(output.getvalue())["refused"][0])

    def test_unset_startup_is_silent_without_filesystem_access(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(launcher_cleanup, "sweep") as sweep:
                with self.assertNoLogs("launcher_cleanup"):
                    launcher_cleanup.audit_startup()
        sweep.assert_not_called()

    def test_startup_audits_without_applying(self) -> None:
        before = self.all_deps()
        with patch.dict(os.environ, self.environment(), clear=True):
            with self.assertLogs("launcher_cleanup", level="WARNING") as logs:
                launcher_cleanup.audit_startup()
        self.assertIn("retained unverified", logs.output[0])
        self.assertEqual(before, self.all_deps())

    def test_startup_missing_current_is_logged_and_keeps_launching(self) -> None:
        with patch.dict(os.environ, {"CORTEX_CLAUDE_DIR": str(self.root)}, clear=True):
            with self.assertLogs("launcher_cleanup", level="WARNING") as logs:
                launcher_cleanup.audit_startup()
        self.assertIn("CLAUDE_PLUGIN_DATA", logs.output[0])

    def test_module_dry_run_argument_reaches_normal_launcher_unchanged(self) -> None:
        arguments = ["launcher.py", "example.module", "--dry-run"]
        with (
            patch.object(sys, "argv", arguments),
            patch.dict(os.environ, {}, clear=True),
        ):
            with patch.object(launcher, "main") as main:
                with patch.object(launcher_cleanup, "cli") as cli:
                    launcher.entrypoint()
        main.assert_called_once_with()
        cli.assert_not_called()
        self.assertEqual(arguments, ["launcher.py", "example.module", "--dry-run"])


class TestCleanupLaunchBoundary(unittest.TestCase):
    def test_hooks_and_workers_never_import_cleanup_even_with_explicit_root(
        self,
    ) -> None:
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("launcher_cleanup"):
                raise AssertionError(f"per-tool cleanup import: {name}")
            return original_import(name, *args, **kwargs)

        for module in (
            "mcp_server.hooks.post_tool_capture",
            "mcp_server.hooks.preemptive_context",
            "mcp_server.hooks.pipeline_impact_bump",
            "mcp_server.hooks.post_commit_reindex",
            "mcp_server.hooks.session_start",
            "example.worker",
        ):
            with (
                self.subTest(module=module),
                patch.object(sys, "argv", ["launcher.py", module]),
                patch.dict(os.environ, {"CORTEX_CLAUDE_DIR": "/unused"}, clear=True),
                patch.object(builtins, "__import__", side_effect=guarded_import),
                patch.object(launcher, "main") as main,
            ):
                launcher.entrypoint()
                main.assert_called_once_with()

    def test_server_audits_once_only_with_explicit_root(self) -> None:
        for environment in ({}, {"CORTEX_CLAUDE_DIR": "/unused"}):
            with (
                self.subTest(environment=environment),
                patch.object(
                    sys, "argv", ["launcher.py", "mcp_server", "--install-deps"]
                ),
                patch.dict(os.environ, environment, clear=True),
                patch.object(launcher_cleanup, "audit_startup") as audit,
                patch.object(launcher, "main") as main,
            ):
                launcher.entrypoint()
                self.assertEqual(audit.call_count, int(bool(environment)))
                main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
