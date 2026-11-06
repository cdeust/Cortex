"""The log relay never runs code from the spawn's cwd (Codex review on PR #897).

A hook spawns from the user's project directory. ``python -m`` without ``-P``
puts that directory first on ``sys.path``, so a planted
``mcp_server/infrastructure/log_relay.py`` would replace the relay."""

from __future__ import annotations

import sys
from pathlib import Path

from mcp_server.infrastructure.log_relay import spawn_logged


def test_a_relay_module_planted_in_the_cwd_is_not_run(tmp_path: Path) -> None:
    project = tmp_path / "project"
    planted = project / "mcp_server" / "infrastructure"
    planted.mkdir(parents=True)
    (project / "mcp_server" / "__init__.py").write_text("")
    (planted / "__init__.py").write_text("")
    marker = tmp_path / "planted-ran"
    (planted / "log_relay.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    log_path = tmp_path / "out.log"

    spawned = spawn_logged(
        [sys.executable, "-c", "print('child output')"], log_path, cwd=str(project)
    )
    spawned.child.wait(timeout=30)
    spawned.relay.wait(timeout=30)

    assert not marker.exists()
    assert "child output" in log_path.read_text(encoding="utf-8")
