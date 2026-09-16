"""The launcher finds a pip even on an interpreter that has none (issue #582).

`_pip_command` ran `sys.executable -m pip`, so from a `uv venv` (no pip module
by design) every install failed with "No module named pip" and the plugin's
private deps directory could not be filled at all. The resolution order is now
installed module, then the wheel the standard library bundles for ensurepip,
then a named error.

source: ADR-1067
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import launcher_pip  # noqa: E402


def _without_module(missing: str):
    """find_spec as if one module were absent, the rest untouched."""
    real = launcher_pip.importlib.util.find_spec

    def find_spec(name: str):
        return None if name == missing else real(name)

    return find_spec


def test_installed_pip_is_preferred(monkeypatch) -> None:
    monkeypatch.setattr(launcher_pip.importlib.util, "find_spec", lambda name: object())

    assert launcher_pip.pip_entry() == [sys.executable, "-m", "pip"]


def test_without_a_pip_module_the_bundled_wheel_is_used(monkeypatch) -> None:
    wheel = launcher_pip.bundled_pip_wheel()
    if wheel is None:
        pytest.skip("this interpreter's stdlib bundles no pip wheel")
    monkeypatch.setattr(
        launcher_pip.importlib.util, "find_spec", _without_module("pip")
    )

    entry = launcher_pip.pip_entry()

    assert entry == [sys.executable, str(wheel / "pip")]


def test_the_bundled_wheel_entry_actually_runs_pip() -> None:
    """The external signal: the resolved command answers as pip."""
    wheel = launcher_pip.bundled_pip_wheel()
    if wheel is None:
        pytest.skip("this interpreter's stdlib bundles no pip wheel")

    result = subprocess.run(
        [sys.executable, str(wheel / "pip"), "--version"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("pip ")


def test_an_interpreter_without_either_is_named_in_the_error(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher_pip.importlib.util, "find_spec", _without_module("pip")
    )
    monkeypatch.setattr(launcher_pip, "bundled_pip_wheel", lambda: None)

    with pytest.raises(FileNotFoundError) as excinfo:
        launcher_pip.pip_entry()

    assert sys.executable in str(excinfo.value)


def test_pip_command_starts_with_the_resolved_entry(monkeypatch) -> None:
    monkeypatch.setattr(launcher_pip, "pip_entry", lambda: ["python-x", "pip-y"])

    command = launcher_pip._pip_command("--target", "/tmp/scratch")

    assert command[:3] == ["python-x", "pip-y", "install"]
    assert command[-2:] == ["--target", "/tmp/scratch"]
