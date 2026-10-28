"""Native launchd rejected worker-start without its own Orca sender identity."""

import plistlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import install_ci_autopilot as installer  # noqa: E402


class InstallerTests(unittest.TestCase):
    def test_launchd_preserves_the_dedicated_coordinator_identity(self):
        # source: launchd probe2026-10-27, no_active_sender_terminal; Orca CLI
        # requires ORCA_TERMINAL_HANDLE for a background orchestration sender.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = SimpleNamespace(
                runtime=root / "runtime",
                repo=root,
                control=root,
                interval=60,
                enable=False,
                coordinator_terminal="term_fixture",
            )
            with (
                patch.object(installer.sys, "platform", "darwin"),
                patch.object(Path, "home", return_value=root),
                patch.object(installer, "copy_runtime"),
            ):
                installer.install(options)
            config = plistlib.loads(
                (
                    root / "Library/LaunchAgents" / f"{installer.LABEL}.plist"
                ).read_bytes()
            )
            self.assertEqual(
                config["EnvironmentVariables"]["ORCA_TERMINAL_HANDLE"], "term_fixture"
            )

    def test_copy_installs_hash_verified_native_reader_dependency_closure(self):
        import hashlib
        import json
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = root / "contract-source.md"
            contract.write_text(
                "## Contract — paste this into the delegation prompt\n"
                "Fixture contract\n---\n\n## Orchestrator side"
            )
            source = Path(installer.__file__).resolve().parent
            expected = {
                name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                for name in installer.RUNTIME
            }
            installer.copy_runtime(SimpleNamespace(contract=contract), root)
            manifest = json.loads((root / "installed-sha256.json").read_text())
            for name in installer.RUNTIME:
                self.assertEqual(
                    hashlib.sha256((root / name).read_bytes()).hexdigest(),
                    expected[name],
                )
                self.assertEqual(manifest[name], expected[name])
            code = (
                "import sys;sys.path.insert(0,sys.argv[1]);"
                "import ci_autopilot,ci_codex_review_event,ci_codex_review_comments;"
                "print('trusted-runtime-imports-ok')"
            )
            done = subprocess.run(
                [sys.executable, "-I", "-B", "-c", code, str(root)],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(done.stdout.strip(), "trusted-runtime-imports-ok")
