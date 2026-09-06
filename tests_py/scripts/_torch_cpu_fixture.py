"""Small bootstrap fixtures: fake pip, fake distributions, no imported ML code."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import launcher_deps_install as install  # noqa: E402
import launcher_pins as pins  # noqa: E402

__all__ = ["SCRIPTS", "CpuInstallFixture", "distribution", "install", "pins"]


def distribution(root: Path, name: str, version: str) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "__init__.py").write_text(f"# fixture {version}", encoding="utf-8")
    metadata = root / f"{name}-{version}.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        f"Name: {name}\nVersion: {version}\n", encoding="utf-8"
    )


class CpuInstallFixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cortex-cpu-bootstrap-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.deps = self.root / "deps"
        self.deps.mkdir()
        self.calls = []
        platform = patch.object(sys, "platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)
        runner = patch.object(install.subprocess, "run", side_effect=self.fake_pip)
        runner.start()
        self.addCleanup(runner.stop)

    def fake_pip(self, command, **options):
        call = {"command": list(command), "environment": options["env"]}
        self.calls.append(call)
        if "download" in command:
            root = Path(command[command.index("--dest") + 1])
            call["requirements"] = Path(command[command.index("-r") + 1]).read_text()
            (root / "torch-2.13.0+cpu-py3-none-any.whl").write_bytes(b"fixture wheel")
        else:
            root = Path(command[command.index("--target") + 1])
            call["constraints"] = (
                Path(command[command.index("-c") + 1]).read_text()
                if "-c" in command
                else ""
            )
            distribution(root, "sentence_transformers", "5.6.1")
            if any("torch-" in item for item in command):
                distribution(root, "torch", "2.13.0+cpu")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
