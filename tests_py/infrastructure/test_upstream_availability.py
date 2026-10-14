"""The server's codebase probe scans siblings of CLAUDE_PROJECT_ROOT only.

The MCP server runs under ``scripts/launcher.py`` (cwd = plugin root), and
only the hook dispatcher exports ``CLAUDE_PROJECT_ROOT``
(``host_dispatch.apply_project_root``). So in the server process the
ADR-0584 sibling source-checkout scan finds a build only when the host
exported that variable; the plugin's own siblings never count.
"""

from __future__ import annotations

from mcp_server.infrastructure import upstream_availability
from tests_py.infrastructure.test_pipeline_discovery_anchor import (
    _built_sibling,
    _layout,
)


def _no_wired_server(monkeypatch) -> None:
    """mcp-connections.json wires no ``codebase`` command."""
    monkeypatch.setattr(
        upstream_availability, "_server_command_runnable", lambda name: False
    )


def test_a_sibling_of_claude_project_root_is_reachable(tmp_path, monkeypatch):
    project, _plugin, _built = _layout(tmp_path, monkeypatch)
    _built_sibling(project.parent)
    _no_wired_server(monkeypatch)
    monkeypatch.setenv("CLAUDE_PROJECT_ROOT", str(project))
    assert upstream_availability.codebase_upstream_available() is True


def test_without_claude_project_root_no_sibling_is_scanned(tmp_path, monkeypatch):
    project, _plugin, _built = _layout(tmp_path, monkeypatch)
    _built_sibling(project.parent)
    _no_wired_server(monkeypatch)
    monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
    assert upstream_availability.codebase_upstream_available() is False
