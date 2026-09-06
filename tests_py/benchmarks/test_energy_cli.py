"""CLI validation must precede optional imports, stream access and sudo."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from benchmarks.energy import run_embedding_energy as cli


SCRIPT = Path(cli.__file__)
PROTOCOL = ["--duration-seconds", "1", "--repetitions", "2"]
# Synthetic CLI inputs only, not measured or recommended carbon factors.
CARBON = ["--carbon-intensity", "1", "--embodied", "1"]


@pytest.mark.parametrize(
    ("provided", "missing"),
    [
        ([], ["--carbon-intensity", "--embodied"]),
        (["--carbon-intensity", "1"], ["--embodied"]),
        (["--embodied", "1"], ["--carbon-intensity"]),
    ],
)
def test_missing_carbon_fails_before_optional_imports(provided, missing):
    # -S excludes site-packages: even NumPy import would fail before argparse.
    result = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), *PROTOCOL, *provided],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert all(option in result.stderr for option in missing)
    assert "ModuleNotFoundError" not in result.stderr
    assert "--external-power-file is required" not in result.stderr


@pytest.mark.parametrize("flag", ["--carbon-intensity", "--embodied"])
@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_invalid_carbon_refused_before_run(flag, value, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run", lambda args: pytest.fail("ran workload"))
    with pytest.raises(SystemExit) as error:
        cli.main([*PROTOCOL, *CARBON, flag, value])
    assert error.value.code != 0
    assert flag in capsys.readouterr().err


def test_validate_only_needs_no_stream_or_model(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_run", lambda args: pytest.fail("ran workload"))
    cli.main([*PROTOCOL, *CARBON, "--validate-only"])
    assert capsys.readouterr().out.strip() == str(cli.DEFAULT_SAMPLE_RATE_MS)


def test_valid_carbon_without_stream_points_to_runner(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main([*PROTOCOL, *CARBON])
    assert error.value.code != 0
    assert "--external-power-file is required; use run.sh" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--duration-seconds", "0"),
        ("--repetitions", "1"),
        ("--batch-size", "0"),
        ("--sample-rate-ms", "0"),
    ],
)
def test_invalid_protocol_refused(flag, value):
    with pytest.raises(SystemExit) as error:
        cli.main([*PROTOCOL, *CARBON, flag, value, "--validate-only"])
    assert error.value.code != 0


@pytest.mark.skipif(shutil.which("zsh") is None, reason="runner requires macOS/zsh")
@pytest.mark.parametrize(
    ("provided", "expected"),
    [
        ([], "--carbon-intensity"),
        (["--carbon-intensity", "1"], "--embodied"),
        (["--embodied", "1"], "--carbon-intensity"),
        ([*CARBON, "--validate-only"], None),
    ],
)
def test_shell_validates_before_sudo(provided, expected, tmp_path):
    marker = tmp_path / "sudo-called"
    fake_sudo = tmp_path / "sudo"
    fake_sudo.write_text('#!/bin/sh\ntouch "$ENERGY_SUDO_MARKER"\nexit 99\n')
    fake_sudo.chmod(0o755)
    env = {
        **os.environ,
        "ENERGY_PYTHON": sys.executable,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "ENERGY_SUDO_MARKER": str(marker),
    }
    result = subprocess.run(
        [shutil.which("zsh"), str(SCRIPT.with_name("run.sh")), *PROTOCOL, *provided],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert not marker.exists()
    if expected is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert expected in result.stderr
