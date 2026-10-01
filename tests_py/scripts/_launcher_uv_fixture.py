"""Shared loader and fakes for scripts/launcher_uv.py tests.

Loaded under the dotted path mutmut derives from the file location (issue
#262), and re-exported through conftest so both test modules share it.

source: ADR-1092"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


@pytest.fixture
def uv_mod(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "scripts.launcher_uv", SCRIPTS / "launcher_uv.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def done(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def fake_uv_site(command: list[str]) -> None:
    """What pip leaves in its --target for the uv wheel: bin/uv."""
    site = Path(command[command.index("--target") + 1])
    (site / "bin").mkdir(parents=True)
    (site / "bin" / "uv").write_text("binary")
