"""``child_command``: how a hook starts a child Python process (issue #667)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.hooks.launcher_command import child_command, launcher_path


def test_with_a_launcher_the_child_runs_through_it(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    launcher = tmp_path / "scripts" / "launcher.py"
    launcher.write_text("# stub\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))

    assert child_command("pkg.mod", "--flag", "x") == [
        sys.executable,
        str(launcher),
        "pkg.mod",
        "--flag",
        "x",
    ]


def test_without_a_launcher_the_child_runs_the_module(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "wheel-runtime"))

    assert child_command("pkg.mod") == [sys.executable, "-m", "pkg.mod"]


def test_the_unset_plugin_root_resolves_to_this_checkouts_launcher(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

    expected = Path(__file__).resolve().parents[2] / "scripts" / "launcher.py"
    assert launcher_path() == expected
    assert expected.exists()
    assert child_command("pkg.mod")[1] == str(expected)


# The real scripts/launcher.py main(), with only the dependency installer
# stubbed (it would pip-install into the test machine), run in-process by
# runpy as ``python launcher.py <module> <args>`` would be.
_LAUNCHER_DRIVER = (
    "import runpy, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import launcher_deps\n"
    "launcher_deps.ensure_deps = launcher_deps.ensure_all_deps = lambda d: None\n"
    "sys.argv = sys.argv[2:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


@pytest.mark.skipif(
    sys.platform == "win32", reason="pass_fds does not exist on Windows"
)
def test_the_launcher_keeps_a_descriptor_passed_with_pass_fds(tmp_path, monkeypatch):
    """The resident capture worker is started with ``pass_fds`` for its
    listener and lease; routing it through the launcher (issue #667) is only
    sound if launcher.main() + runpy leave an inherited descriptor open."""
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path))
    launcher = launcher_path()
    command = child_command("tests_py.hooks.fd_probe_child", "--fd", "FD")
    read_end, write_end = os.pipe()
    try:
        command[command.index("FD")] = str(write_end)
        argv = [
            command[0],
            "-c",
            _LAUNCHER_DRIVER,
            str(launcher.parent),
            *command[1:],
        ]
        done = subprocess.run(
            argv, pass_fds=(write_end,), capture_output=True, text=True, check=False
        )
        os.close(write_end)
        write_end = -1
        assert done.returncode == 0, done.stderr
        assert os.read(read_end, 64) == b"carried"
    finally:
        os.close(read_end)
        if write_end != -1:
            os.close(write_end)
