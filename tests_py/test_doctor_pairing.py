"""Plugin/runtime pairing check contracts. Source: issue #729 (slice 3)."""

import json
from importlib import metadata
from pathlib import Path

import pytest

from mcp_server import doctor, doctor_pairing

REPO = Path(__file__).resolve().parents[1]


def _plugin(tmp_path, manifest="1.2.3", project="1.2.3"):
    """A Claude plugin directory: manifest, pyproject and an mcp_server package."""
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / "mcp_server").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "hypermnesia-mcp", "version": manifest})
    )
    (plugin / "pyproject.toml").write_text(f'[project]\nversion = "{project}"\n')
    return plugin


def _runs_from(monkeypatch, package, dist=None):
    monkeypatch.setattr(doctor_pairing.mcp_server, "__file__", str(package / "x"))

    def distribution(name):
        if dist is None:
            raise metadata.PackageNotFoundError(name)
        return dist

    monkeypatch.setattr(doctor_pairing.metadata, "distribution", distribution)


def _check(env):
    return doctor_pairing.plugin_pairing(doctor.Check, env)


def test_outside_the_claude_plugin_there_is_no_pairing_to_check():
    result = _check({})
    assert (result.ok, result.optional) == (True, True)
    assert "CLAUDE_PLUGIN_ROOT unset" in result.detail


def test_the_plugin_running_its_own_source_tree_is_supported(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    _runs_from(monkeypatch, plugin / "mcp_server")
    result = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)})
    assert result.ok, result.detail
    assert "Claude plugin 1.2.3 runs its own mcp_server 1.2.3" in result.detail
    assert str(plugin / "pyproject.toml") in result.detail


def test_code_imported_from_elsewhere_is_unsupported(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    other = tmp_path / "site" / "mcp_server"
    other.mkdir(parents=True)
    _runs_from(monkeypatch, other)
    result = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)})
    assert (result.ok, result.optional) == (False, True)
    assert f"imports mcp_server from {other.resolve()}" in result.detail
    assert "scripts/launcher.py mcp_server.doctor" in result.fix


def test_a_manifest_ahead_of_its_code_is_unsupported(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, manifest="1.2.4", project="1.2.3")
    _runs_from(monkeypatch, plugin / "mcp_server")
    result = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)})
    assert not result.ok
    assert "declares 1.2.4, its mcp_server is 1.2.3" in result.detail
    assert result.fix == doctor_pairing._REINSTALL


def test_an_installed_wheel_in_the_plugin_gives_its_own_version(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, project="0.0.0")
    info = plugin / "hypermnesia_mcp-1.2.3.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: hypermnesia-mcp\nVersion: 1.2.3\n")
    _runs_from(monkeypatch, plugin / "mcp_server", metadata.PathDistribution(info))
    result = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)})
    assert result.ok, result.detail
    assert "(installed hypermnesia-mcp)" in result.detail


@pytest.mark.parametrize("manifest", ["{", '{"name": "x"}', "[]"])
def test_an_unreadable_manifest_fails_and_names_why(tmp_path, monkeypatch, manifest):
    plugin = _plugin(tmp_path)
    (plugin / ".claude-plugin" / "plugin.json").write_text(manifest)
    _runs_from(monkeypatch, plugin / "mcp_server")
    result = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)})
    assert not result.ok
    assert result.detail.startswith("cannot read the Claude plugin pairing: ")


def test_a_missing_manifest_fails(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    (plugin / ".claude-plugin" / "plugin.json").unlink()
    _runs_from(monkeypatch, plugin / "mcp_server")
    assert not _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}).ok


def test_this_checkout_is_a_supported_pairing():
    """The repository is the Claude plugin directory: its manifest and its
    pyproject must agree, which is the pairing a plugin install receives."""
    assert Path(doctor_pairing.mcp_server.__file__).resolve().parent == (
        REPO / "mcp_server"
    )
    result = _check({"CLAUDE_PLUGIN_ROOT": str(REPO)})
    assert result.ok, result.detail


def test_both_check_lists_run_the_pairing_check():
    assert doctor._plugin_pairing in doctor.CHECKS
    assert doctor._plugin_pairing in doctor.SQLITE_CHECKS
