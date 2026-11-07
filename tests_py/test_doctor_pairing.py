"""Plugin/runtime pairing check contracts. Source: issue #729 (slice 3)."""

import json
import sys
from importlib import metadata
from pathlib import Path

import pytest

from mcp_server import doctor, doctor_pairing

REPO = Path(__file__).resolve().parents[1]
NAME = "Plugin/runtime pairing"
REINSTALL = (
    "Update or reinstall the Claude plugin so its directory holds the code its "
    "manifest declares"
)


def _plugin(tmp_path, manifest="1.2.3", project='version = "1.2.3"'):
    """A Claude plugin directory: manifest, pyproject and an mcp_server package."""
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / "mcp_server").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "hypermnesia-mcp", "version": manifest})
    )
    (plugin / "pyproject.toml").write_text(f"[project]\n{project}\n")
    return plugin


def _runs_from(monkeypatch, package, dist=None):
    monkeypatch.setattr(doctor_pairing.mcp_server, "__file__", str(package / "x"))

    def distribution(name):
        if dist is None:
            raise metadata.PackageNotFoundError(name)
        return dist

    monkeypatch.setattr(doctor_pairing.metadata, "distribution", distribution)


def _check(env, *, ok, fix=""):
    """Run the check; every result is optional, named, and carries ``fix``."""
    result = doctor_pairing.plugin_pairing(doctor.Check, env)
    assert (result.name, result.ok, result.optional) == (NAME, ok, True)
    assert result.fix == fix
    return result.detail


@pytest.mark.parametrize("env", [{}, {"CLAUDE_PLUGIN_ROOT": ""}])
def test_outside_the_claude_plugin_there_is_no_pairing_to_check(env):
    detail = _check(env, ok=True)
    assert detail == (
        "CLAUDE_PLUGIN_ROOT unset: not launched by the Claude plugin, no pairing"
    )


def test_the_plugin_running_its_own_source_tree_is_supported(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    _runs_from(monkeypatch, plugin / "mcp_server")
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=True)
    assert detail == (
        "Claude plugin 1.2.3 runs its own mcp_server 1.2.3 "
        f"({plugin.resolve() / 'pyproject.toml'})"
    )


def test_code_imported_from_elsewhere_is_unsupported(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    other = tmp_path / "site" / "mcp_server"
    other.mkdir(parents=True)
    _runs_from(monkeypatch, other)
    root = plugin.resolve()
    fix = (
        f"Run the doctor through the plugin launcher (`python3 {root}/scripts/"
        "launcher.py mcp_server.doctor`), which puts the plugin directory first "
        "on the import path, or unset CLAUDE_PLUGIN_ROOT outside the plugin"
    )
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=False, fix=fix)
    assert detail == (
        f"Claude plugin 1.2.3 at {root}, but this process imports mcp_server "
        f"from {other.resolve()}: unsupported pairing"
    )


def test_a_manifest_ahead_of_its_code_is_unsupported(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, manifest="1.2.4")
    _runs_from(monkeypatch, plugin / "mcp_server")
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=False, fix=REINSTALL)
    assert detail.startswith(
        "Claude plugin manifest declares 1.2.4, its mcp_server is 1.2.3 ("
    )
    assert detail.endswith("): unsupported pairing")


def test_an_installed_wheel_in_the_plugin_gives_its_own_version(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path, project='version = "0.0.0"')
    info = plugin / "hypermnesia_mcp-1.2.3.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: hypermnesia-mcp\nVersion: 1.2.3\n")
    _runs_from(monkeypatch, plugin / "mcp_server", metadata.PathDistribution(info))
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=True)
    assert detail.endswith("mcp_server 1.2.3 (installed hypermnesia-mcp)")


@pytest.mark.parametrize(
    "manifest", [b"{", b'{"name": "x"}', b"[]", b'{"version": ""}', b'{"version": 1}']
)
def test_a_manifest_without_a_version_fails(tmp_path, monkeypatch, manifest):
    plugin = _plugin(tmp_path)
    (plugin / ".claude-plugin" / "plugin.json").write_bytes(manifest)
    _runs_from(monkeypatch, plugin / "mcp_server")
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=False, fix=REINSTALL)
    assert detail.startswith("cannot read the Claude plugin pairing: ")
    if manifest != b"{":
        assert detail.endswith("plugin.json declares no version")


def test_a_non_ascii_manifest_is_read_as_utf8(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    manifest = {"description": "mémoire", "version": "1.2.3"}
    (plugin / ".claude-plugin" / "plugin.json").write_bytes(
        json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    )
    _runs_from(monkeypatch, plugin / "mcp_server")
    _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=True)


@pytest.mark.parametrize("project", ['version = ""', "version = 1", 'name = "x"'])
def test_a_pyproject_without_a_version_fails(tmp_path, monkeypatch, project):
    plugin = _plugin(tmp_path, project=project)
    _runs_from(monkeypatch, plugin / "mcp_server")
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=False, fix=REINSTALL)
    assert detail.endswith("pyproject.toml declares no [project] version")


def test_a_pyproject_whose_project_is_not_a_table_fails(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    (plugin / "pyproject.toml").write_text('project = "x"\n')
    _runs_from(monkeypatch, plugin / "mcp_server")
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=False, fix=REINSTALL)
    assert detail.endswith("pyproject.toml declares no [project] version")


def test_a_missing_manifest_fails(tmp_path, monkeypatch):
    plugin = _plugin(tmp_path)
    (plugin / ".claude-plugin" / "plugin.json").unlink()
    _runs_from(monkeypatch, plugin / "mcp_server")
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=False, fix=REINSTALL)
    assert "plugin.json" in detail


def test_this_checkout_is_a_supported_pairing():
    """The repository is the Claude plugin directory: its manifest and its
    pyproject must agree, which is the pairing a plugin install receives."""
    assert Path(doctor_pairing.mcp_server.__file__).resolve().parent == (
        REPO / "mcp_server"
    )
    _check({"CLAUDE_PLUGIN_ROOT": str(REPO)}, ok=True)


def test_both_check_lists_run_the_pairing_check():
    assert doctor._plugin_pairing in doctor.CHECKS
    assert doctor._plugin_pairing in doctor.SQLITE_CHECKS


def _symlink_loop(tmp_path):
    """Two links naming each other; resolve() raises RuntimeError up to 3.12."""
    (tmp_path / "loop-a").symlink_to(tmp_path / "loop-b")
    (tmp_path / "loop-b").symlink_to(tmp_path / "loop-a")
    return tmp_path / "loop-a"


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink privilege is not assumed on Windows"
)
def test_a_plugin_root_in_a_symlink_loop_fails_the_check_only(tmp_path):
    loop = _symlink_loop(tmp_path)
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(loop)}, ok=False, fix=REINSTALL)
    assert detail.startswith("cannot read the Claude plugin pairing: ")
    assert str(loop) in detail


def test_a_distribution_installed_elsewhere_reads_the_pyproject(tmp_path, monkeypatch):
    """A hypermnesia-mcp wheel in another site-packages does not speak for the
    plugin's own code: the version comes from the plugin's pyproject."""
    plugin = _plugin(tmp_path)
    site = tmp_path / "site"
    (site / "mcp_server").mkdir(parents=True)
    info = site / "hypermnesia_mcp-9.9.9.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: hypermnesia-mcp\nVersion: 9.9.9\n")
    _runs_from(monkeypatch, plugin / "mcp_server", metadata.PathDistribution(info))
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(plugin)}, ok=True)
    assert detail == (
        "Claude plugin 1.2.3 runs its own mcp_server 1.2.3 "
        f"({plugin.resolve() / 'pyproject.toml'})"
    )


def test_a_missing_plugin_root_is_named_not_its_manifest(tmp_path):
    """The strict resolve fails on the root itself, so the failure names the
    directory that is missing, not a manifest path inside it."""
    missing = tmp_path / "no-such-plugin"
    detail = _check({"CLAUDE_PLUGIN_ROOT": str(missing)}, ok=False, fix=REINSTALL)
    assert detail.startswith("cannot read the Claude plugin pairing: ")
    assert missing.name in detail
    assert "plugin.json" not in detail
