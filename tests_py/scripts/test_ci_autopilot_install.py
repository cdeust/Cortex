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
