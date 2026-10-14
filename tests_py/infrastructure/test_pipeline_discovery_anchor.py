"""The sibling source-checkout scan is anchored on the session's project root.

ADR-0584 preserves the original comment: the ``_SOURCE_DIRS`` entries are
"relative to each user's working dir (the MCP server runs in the user's
project root)". That premise is false: a hook runs under
``scripts/launcher.py``, which ``chdir``s to the plugin root first, so a scan
relative to ``os.getcwd()`` probed the plugin's siblings, not the project's:
from the main checkout it found ``../ai-architect-mcp-codebase`` and the
SessionStart hook spawned a detached ingest of the plugin root (the leak the
#679 guard reported, 2026-10-14). These tests pin the anchor to the argument.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.infrastructure import pipeline_discovery
from tests_py.infrastructure.test_pipeline_discovery import _isolate_real_installs

_SIBLING = "../ai-architect-mcp-codebase"


def _built_sibling(parent: Path) -> Path:
    """An executable pipeline build at ``parent/ai-architect-mcp-codebase``."""
    built = parent / "ai-architect-mcp-codebase" / pipeline_discovery._BUILT_RELATIVE[0]
    built.parent.mkdir(parents=True)
    built.write_text("#!/bin/sh\n", encoding="utf-8")
    built.chmod(0o755)
    return built


def _layout(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    """``(project, plugin, built)``: the build sits next to ``plugin`` only,
    and the process cwd is ``plugin``, as under the launcher."""
    _isolate_real_installs(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline_discovery.shutil, "which", lambda name: None)
    monkeypatch.setattr(pipeline_discovery, "_SOURCE_DIRS", (_SIBLING,))
    project = tmp_path / "projects" / "app"
    project.mkdir(parents=True)
    plugin = tmp_path / "plugins" / "cortex"
    plugin.mkdir(parents=True)
    built = _built_sibling(plugin.parent)
    monkeypatch.chdir(plugin)
    return project, plugin, built


def test_a_sibling_of_the_cwd_is_not_a_sibling_of_the_project(tmp_path, monkeypatch):
    project, _plugin, _built = _layout(tmp_path, monkeypatch)
    assert pipeline_discovery.discover_pipeline_command(str(project)) is None


def test_a_sibling_of_the_project_is_found_from_any_cwd(tmp_path, monkeypatch):
    project, _plugin, _built = _layout(tmp_path, monkeypatch)
    built = _built_sibling(project.parent)
    assert pipeline_discovery.discover_pipeline_command(str(project)) == [str(built)]


def test_no_project_root_scans_no_sibling(tmp_path, monkeypatch):
    _layout(tmp_path, monkeypatch)
    assert pipeline_discovery.discover_pipeline_command(None) is None
