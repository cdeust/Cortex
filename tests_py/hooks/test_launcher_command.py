"""``child_command``: how a hook starts a child Python process (issue #667)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.hooks.launcher_command import child_command, launcher_path
from tests_py._launcher_ready import ready_launcher_argv


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

    assert child_command("pkg.mod") == [sys.executable, "-P", "-m", "pkg.mod"]


def test_without_a_launcher_a_module_in_the_cwd_is_not_run(tmp_path, monkeypatch):
    """A hook's cwd is the user's project: a planted package there must not
    shadow the worker (Codex security review on PR #897)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "wheel-runtime"))
    project = tmp_path / "project"
    (project / "planted_pkg").mkdir(parents=True)
    (project / "planted_pkg" / "__init__.py").write_text("")
    marker = tmp_path / "ran"
    (project / "planted_pkg" / "mod.py").write_text(
        f"open({str(marker)!r}, 'w').close()\n"
    )

    result = subprocess.run(
        child_command("planted_pkg.mod"), cwd=project, capture_output=True
    )

    assert result.returncode != 0
    assert not marker.exists()


def test_the_unset_plugin_root_resolves_to_this_checkouts_launcher(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

    expected = Path(__file__).resolve().parents[2] / "scripts" / "launcher.py"
    assert launcher_path() == expected
    assert expected.exists()
    assert child_command("pkg.mod")[1] == str(expected)


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
        argv = ready_launcher_argv(launcher, *command[2:])
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
