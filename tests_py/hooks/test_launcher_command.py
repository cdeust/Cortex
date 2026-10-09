"""``child_command``: how a hook starts a child Python process (issue #667)."""

from __future__ import annotations

import sys
from pathlib import Path

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
