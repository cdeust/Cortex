"""Installation harness portability: actual command boundaries, no native-OS claim."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "install_e2e"))
try:
    import host
    import evidence

    spec = importlib.util.spec_from_file_location(
        "install_probe", SCRIPTS / "install_e2e/run.py"
    )
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
finally:
    sys.path.remove(str(SCRIPTS / "install_e2e"))
    sys.path.remove(str(SCRIPTS))


class InstallPlatforms(unittest.TestCase):
    def test_npm_cmd_uses_installed_package_entrypoint_and_node_without_a_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shim = root / "claude.cmd"
            shim.touch()
            package = root / "node_modules/@anthropic-ai/claude-code"
            package.mkdir(parents=True)
            (package / "cli.js").touch()
            (package / "package.json").write_text(
                json.dumps({"bin": {"claude": "cli.js"}})
            )
            with patch.object(
                host.shutil, "which", side_effect=[str(shim), "/system/node.exe"]
            ):
                command = host._claude_command()
            self.assertEqual(
                command, ("/system/node.exe", str((package / "cli.js").resolve()))
            )

    def test_pinned_npm_package_executes_its_native_binary_without_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shim = root / "claude.cmd"
            shim.touch()
            package = root / "node_modules/@anthropic-ai/claude-code"
            (package / "bin").mkdir(parents=True)
            entry = package / "bin/claude.exe"
            entry.touch()
            (package / "package.json").write_text(
                json.dumps({"bin": {"claude": "bin/claude.exe"}})
            )
            with patch.object(host.shutil, "which", return_value=str(shim)) as which:
                self.assertEqual(host._claude_command(), (str(entry.resolve()),))
            which.assert_called_once_with("claude")

    def test_npm_entrypoint_cannot_escape_installed_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shim = root / "claude.cmd"
            shim.touch()
            package = root / "node_modules/@anthropic-ai/claude-code"
            package.mkdir(parents=True)
            (package / "package.json").write_text(
                json.dumps({"bin": {"claude": "../../elsewhere.js"}})
            )
            with (
                patch.object(host.shutil, "which", return_value=str(shim)),
                self.assertRaisesRegex(RuntimeError, "outside"),
            ):
                host._claude_command()

    def test_windows_keeps_system_resolution_but_isolates_app_state_and_database(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            inherited = {
                "PATH": "system-tools",
                "SystemRoot": "C:/Windows",
                "USERNAME": "runneradmin",
                "USERDOMAIN": "BUILDHOST",
                "GH_TOKEN": "must-not-be-inherited",
                "DATABASE_URL": "postgresql://production",
                "PYTHONPATH": "other-runtime",
            }
            with patch.dict(host.os.environ, inherited, clear=True):
                result = host._machine_environment(home, home / "python", windows=True)
            self.assertIn("system-tools", result["PATH"])
            self.assertEqual(result["SystemRoot"], "C:/Windows")
            self.assertEqual(result["USERNAME"], "runneradmin")
            self.assertEqual(result["USERDOMAIN"], "BUILDHOST")
            self.assertNotIn("GH_TOKEN", result)
            self.assertEqual(result["USERPROFILE"], str(home))
            self.assertEqual(result["APPDATA"], str(home / "appdata"))
            self.assertNotIn("DATABASE_URL", result)
            self.assertNotIn("PYTHONPATH", result)

    def test_setup_diagnostics_are_collected_only_for_a_failed_setup(self):
        machine = SimpleNamespace(
            cli=("claude",), env={}, plugin_data=Path("data"), work=Path("work")
        )
        for code in (0, 1):
            with (
                self.subTest(code=code),
                patch.object(probe.init_plugin, "init", return_value=code),
                patch.object(
                    probe.evidence,
                    "setup_failure_logs",
                    return_value={"setup.log": "base install failed"},
                ) as logs,
            ):
                result = probe._init(machine, [])
            self.assertEqual(result["returncode"], code)
            if code:
                logs.assert_called_once_with(machine.plugin_data, machine.work)
                self.assertEqual(
                    result["failure_logs"]["setup.log"], "base install failed"
                )
            else:
                logs.assert_not_called()
                self.assertNotIn("failure_logs", result)

    def test_native_python_alias_remains_beside_its_venv_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def create(command, **kwargs):
                runtime = Path(command[-1])
                (runtime / "Scripts").mkdir(parents=True)
                (runtime / "pyvenv.cfg").write_text("home = pinned-python")
                (runtime / "Scripts/python.exe").write_bytes(b"fixture executable")

            with patch.object(host.subprocess, "run", side_effect=create) as run:
                scripts = host._windows_python(root, "pinned-python")
            self.assertEqual(
                run.call_args.args[0][:4],
                ["pinned-python", "-m", "venv", "--without-pip"],
            )
            self.assertEqual(
                (scripts / "python3.exe").read_bytes(),
                (scripts / "python.exe").read_bytes(),
            )
            self.assertTrue((scripts.parent / "pyvenv.cfg").exists())

    def test_cli_failure_is_preserved_and_arguments_are_not_shell_interpreted(self):
        machine = SimpleNamespace(
            cli=("node.exe", "C:/with spaces/cli.js"), project=Path("."), env={}
        )
        with patch.object(
            host.subprocess,
            "run",
            return_value=SimpleNamespace(
                returncode=9, stdout="", stderr="native failure"
            ),
        ) as run:
            result = host.run_claude(machine, [], "plugin", "install", "fixture@market")
        self.assertEqual(result.returncode, 9)
        self.assertEqual(
            run.call_args.args[0], [*machine.cli, "plugin", "install", "fixture@market"]
        )
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertIn("native failure", result.output)

    def test_store_expectation_requires_native_windows_fallback_and_keeps_pg_elsewhere(
        self,
    ):
        pg = {"system_message": "Cortex ready: PostgreSQL memory store, 0 memories"}
        sqlite = {
            "system_message": (
                "Cortex ready: SQLite memory at /private/memory.db, 0 memories\n"
                "SQLite fallback: managed PostgreSQL unavailable here (Windows)"
            )
        }
        self.assertTrue(probe._supported_store(pg, windows=False))
        self.assertFalse(probe._supported_store(pg, windows=True))
        self.assertTrue(probe._supported_store(sqlite, windows=True))
        self.assertFalse(probe._supported_store(sqlite, windows=False))
        self.assertFalse(
            probe._supported_store(
                {"system_message": sqlite["system_message"].splitlines()[0]},
                windows=True,
            )
        )

    def test_windows_process_paths_match_across_slash_and_case_conventions(self):
        rows = [
            (1234, "python C:/OWNED/launcher.py"),
            (5678, "python C:/unrelated/private.py"),
        ]
        with (
            patch.object(evidence.os, "name", "nt"),
            patch.object(evidence, "_windows_processes", return_value=rows),
        ):
            found = evidence._plugin_processes(("c:\\owned\\",))
        self.assertEqual(found, ["1234 python C:/OWNED/launcher.py"])

    def test_windows_process_query_returns_only_filtered_records_and_fails_loudly(self):
        rows = [{"ProcessId": 1234, "CommandLine": "python C:/owned/launcher.py"}]
        with patch.object(
            evidence.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=json.dumps(rows)),
        ) as run:
            self.assertEqual(
                evidence._windows_processes(("C:/owned/",)),
                [(1234, rows[0]["CommandLine"])],
            )
        self.assertEqual(
            json.loads(run.call_args.kwargs["env"]["CORTEX_INSTALL_PROCESS_MARKERS"]),
            ["c:/owned/"],
        )
        self.assertTrue(run.call_args.kwargs["check"])
        with (
            patch.object(
                evidence.subprocess, "run", side_effect=OSError("CIM unavailable")
            ),
            self.assertRaisesRegex(OSError, "CIM unavailable"),
        ):
            evidence._windows_processes(("C:/owned/",))


if __name__ == "__main__":
    unittest.main()
