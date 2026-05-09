"""Tests for scripts/launcher.py path resolution.

Verifies _resolve_paths() correctly picks plugin_root under three
scenarios:
  1. CLAUDE_PLUGIN_ROOT set to a valid directory → use it
  2. CLAUDE_PLUGIN_ROOT unset → fall back to __file__.parent.parent
  3. CLAUDE_PLUGIN_ROOT set to invalid (nonexistent) → fall back

Also verifies CLAUDE_PLUGIN_DATA controls deps_dir location.

Source: Discord report 2026-05-09 — `.mcp.json` now uses
${CLAUDE_PLUGIN_ROOT} substitution; we must confirm the launcher
honours it correctly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = REPO_ROOT / "scripts" / "launcher.py"


@pytest.fixture
def launcher_module():
    """Load scripts/launcher.py as a module without executing main()."""
    spec = importlib.util.spec_from_file_location("_cortex_launcher", LAUNCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_var_set_with_valid_path(launcher_module, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    plugin_root, deps_dir = launcher_module._resolve_paths()
    assert plugin_root == str(tmp_path)
    assert deps_dir == str(tmp_path / "deps")


def test_env_var_unset_falls_back_to_file_parent(launcher_module, monkeypatch):
    """No CLAUDE_PLUGIN_ROOT → resolve via __file__'s grandparent."""
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    plugin_root, deps_dir = launcher_module._resolve_paths()
    # Should resolve to the repo root (launcher.py's grandparent).
    assert plugin_root == str(REPO_ROOT)
    assert deps_dir == str(REPO_ROOT / "deps")


def test_env_var_set_but_invalid_falls_back(launcher_module, monkeypatch, tmp_path):
    """CLAUDE_PLUGIN_ROOT pointing at a non-existent dir → fall back."""
    bogus = tmp_path / "does_not_exist"
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(bogus))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    plugin_root, _ = launcher_module._resolve_paths()
    # Falls back to the script's grandparent, not the bogus path.
    assert plugin_root == str(REPO_ROOT)


def test_env_var_set_to_empty_string_falls_back(launcher_module, monkeypatch):
    """Empty string is treated as unset (covers shell `export VAR=` case)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "")
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    plugin_root, _ = launcher_module._resolve_paths()
    assert plugin_root == str(REPO_ROOT)


def test_plugin_data_redirects_deps_dir(launcher_module, monkeypatch, tmp_path):
    """CLAUDE_PLUGIN_DATA → deps_dir lives there, not under plugin_root."""
    plugin_root_dir = tmp_path / "plugin_root"
    plugin_root_dir.mkdir()
    plugin_data_dir = tmp_path / "plugin_data"
    plugin_data_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root_dir))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data_dir))
    plugin_root, deps_dir = launcher_module._resolve_paths()
    assert plugin_root == str(plugin_root_dir)
    assert deps_dir == str(plugin_data_dir / "deps")
