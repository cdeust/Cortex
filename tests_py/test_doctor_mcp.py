"""Tests for `cortex-doctor mcp` MCP startup diagnostics.

Each individual check is exercised against fixture state — no live
plugin install required. Covers happy path + each failure mode named in
the Discord issue: missing installed_plugins.json, missing key, stale
installPath, missing launcher, launcher startup error.

Source: Discord report 2026-05-09 (MCP server "✘ failed" silently).
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_server.doctor_mcp import (
    McpCheck,
    McpReport,
    _check_claude_plugin_root_env,
    _check_cortex_plugin_entry,
    _check_critical_imports,
    _check_database_url,
    _check_install_path,
    _check_installed_plugins_json,
    _check_launcher_smoke,
    _check_optional_imports,
    _check_pg_extensions,
    _check_pg_reachable,
    _check_python_interpreter,
    _print_human,
    collect_mcp_report,
    run_mcp,
)


# --- python interpreter -------------------------------------------------


def test_python_interpreter_found():
    """The test env must have at least one of python3/python on PATH."""
    check = _check_python_interpreter()
    assert check.ok is True
    assert "python" in check.detail


# --- installed_plugins.json --------------------------------------------


def test_installed_plugins_json_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    check, data = _check_installed_plugins_json()
    assert check.ok is False
    assert "not found" in check.detail
    assert data is None


def test_installed_plugins_json_corrupt(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = tmp_path / ".claude" / "plugins"
    p.mkdir(parents=True)
    (p / "installed_plugins.json").write_text("{not valid json")
    check, data = _check_installed_plugins_json()
    assert check.ok is False
    assert "invalid JSON" in check.detail
    assert data is None


def test_installed_plugins_json_happy(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = tmp_path / ".claude" / "plugins"
    p.mkdir(parents=True)
    (p / "installed_plugins.json").write_text('{"plugins": {}}')
    check, data = _check_installed_plugins_json()
    assert check.ok is True
    assert data == {"plugins": {}}


# --- cortex plugin entry ------------------------------------------------


def test_cortex_entry_key_missing():
    data = {"plugins": {"some-other-plugin": [{"installPath": "/x"}]}}
    check, install_path = _check_cortex_plugin_entry(data)
    assert check.ok is False
    assert "missing" in check.detail
    assert "some-other-plugin" in check.detail
    assert install_path is None


def test_cortex_entry_data_none():
    check, install_path = _check_cortex_plugin_entry(None)
    assert check.ok is False
    assert install_path is None


def test_cortex_entry_install_path_missing():
    data = {"plugins": {"cortex@cortex-plugins": [{}]}}
    check, install_path = _check_cortex_plugin_entry(data)
    assert check.ok is False
    assert "installPath" in check.detail
    assert install_path is None


def test_cortex_entry_happy():
    data = {
        "plugins": {
            "cortex@cortex-plugins": [{"installPath": "/some/path"}],
        }
    }
    check, install_path = _check_cortex_plugin_entry(data)
    assert check.ok is True
    assert install_path == "/some/path"


# --- installPath validation --------------------------------------------


def test_install_path_does_not_exist(tmp_path):
    nonexistent = str(tmp_path / "nonexistent")
    check = _check_install_path(nonexistent)
    assert check.ok is False
    assert "does not exist" in check.detail


def test_install_path_no_launcher(tmp_path):
    (tmp_path / "scripts").mkdir()  # but no launcher.py
    check = _check_install_path(str(tmp_path))
    assert check.ok is False
    assert "launcher.py missing" in check.detail


def test_install_path_happy(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "launcher.py").write_text("# stub")
    check = _check_install_path(str(tmp_path))
    assert check.ok is True


def test_install_path_none():
    check = _check_install_path(None)
    assert check.ok is False


# --- CLAUDE_PLUGIN_ROOT env --------------------------------------------


def test_claude_plugin_root_present(monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/some/plugin/root")
    check = _check_claude_plugin_root_env()
    assert check.ok is True
    assert "/some/plugin/root" in check.detail


def test_claude_plugin_root_absent_is_not_failure(monkeypatch):
    """Absence is informational — the var is set only at MCP/hook spawn."""
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    check = _check_claude_plugin_root_env()
    assert check.ok is True  # not a failure
    assert "not set" in check.detail


# --- launcher smoke -----------------------------------------------------


def test_launcher_smoke_no_install_path():
    check = _check_launcher_smoke(None)
    assert check.ok is False


def test_launcher_smoke_real_launcher():
    """Probe the real launcher.py in this checkout — should print Usage."""
    repo = Path(__file__).resolve().parents[1]
    check = _check_launcher_smoke(str(repo))
    assert check.ok is True, f"unexpected: {check.detail} / {check.error}"
    assert "loads cleanly" in check.detail


def test_launcher_smoke_missing_launcher(tmp_path):
    check = _check_launcher_smoke(str(tmp_path))
    assert check.ok is False
    assert "missing" in check.detail


def test_launcher_smoke_broken_launcher(tmp_path):
    """A launcher.py that crashes on import → smoke probe catches it."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "launcher.py").write_text(
        "import sys\nraise RuntimeError('synthetic boom')\n"
    )
    check = _check_launcher_smoke(str(tmp_path))
    assert check.ok is False
    assert "synthetic boom" in check.error or check.error  # error captured


# --- DATABASE_URL -------------------------------------------------------


def test_database_url_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    check = _check_database_url()
    assert check.ok is False
    assert "not set" in check.detail


def test_database_url_wrong_scheme(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql://localhost/foo")
    check = _check_database_url()
    assert check.ok is False
    assert "scheme" in check.detail


def test_database_url_happy(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/cortex")
    check = _check_database_url()
    assert check.ok is True


# --- run_mcp / report --------------------------------------------------


def test_collect_mcp_report_returns_report():
    report = collect_mcp_report()
    assert isinstance(report, McpReport)
    assert len(report.checks) >= 5
    for c in report.checks:
        assert isinstance(c, McpCheck)


def test_run_mcp_json_output(capsys, monkeypatch, tmp_path):
    """--json flag emits parseable JSON."""
    monkeypatch.setenv("HOME", str(tmp_path))  # force missing plugins.json
    rc = run_mcp(json_output=True)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "checks" in parsed
    assert "ok" in parsed
    # With HOME redirected to empty dir, plugins.json is missing → fail.
    assert parsed["ok"] is False
    assert rc == 1


def test_run_mcp_human_output(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = run_mcp(json_output=False)
    out = capsys.readouterr().out
    assert "Cortex doctor" in out
    assert "MCP startup diagnostics" in out
    assert rc == 1  # missing plugins.json fails


def test_run_mcp_subcommand_dispatch(monkeypatch, capsys, tmp_path):
    """`cortex-doctor mcp` via the entry point dispatches to run_mcp."""
    from mcp_server import doctor

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["cortex-doctor", "mcp", "--json"])
    rc = doctor.run()
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "checks" in parsed
    assert isinstance(rc, int)


# --- postgresql reachability -------------------------------------------


def test_pg_reachable_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    check = _check_pg_reachable()
    assert check.ok is False
    assert "DATABASE_URL not set" in check.detail


def test_pg_reachable_bad_dsn(monkeypatch):
    """A DSN pointing at an invalid host yields a verbatim error string."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://nobody@127.0.0.1:1/doesnotexist?connect_timeout=1",
    )
    check = _check_pg_reachable()
    assert check.ok is False
    # Either psycopg is missing (older test env) or the connect failed
    # — both are acceptable paths; both must surface a real error string.
    assert check.error, "expected a verbatim error from psycopg or import"


def test_pg_extensions_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    check = _check_pg_extensions()
    assert check.ok is False
    assert "DATABASE_URL not set" in check.detail


# --- critical imports --------------------------------------------------


def test_critical_imports_returns_check():
    """Hard-deps check returns a real McpCheck — pass or fail.

    We don't assert ok=True because the test env may genuinely lack a
    dep. We assert the check has a real signal either way.
    """
    check = _check_critical_imports()
    assert isinstance(check, McpCheck)
    if not check.ok:
        # Failure must name the missing module(s).
        assert "missing" in check.detail


def test_optional_imports_warn_severity():
    """Optional deps check is severity=warn, never severity=fail."""
    check = _check_optional_imports()
    if not check.ok:
        assert check.severity == "warn", (
            "optional deps must be warn-severity so a missing "
            "sentence_transformers does not block MCP startup"
        )


# --- printing / colour / copy header -----------------------------------


def test_print_human_with_copy_header(monkeypatch, tmp_path, capsys):
    """--copy header is printed before the rest of the output."""
    monkeypatch.setenv("HOME", str(tmp_path))
    report = collect_mcp_report()
    _print_human(report, copy_header=True)
    out = capsys.readouterr().out
    assert "cortex-doctor mcp output" in out
    # And the regular header still shows up.
    assert "MCP startup diagnostics" in out


def test_print_human_without_copy_header(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    report = collect_mcp_report()
    _print_human(report, copy_header=False)
    out = capsys.readouterr().out
    assert "please paste" not in out


def test_print_human_no_color_in_pipe(monkeypatch, tmp_path, capsys):
    """When stdout is not a TTY (capsys), no ANSI escapes leak."""
    monkeypatch.setenv("HOME", str(tmp_path))
    report = collect_mcp_report()
    _print_human(report)
    out = capsys.readouterr().out
    assert "\033[" not in out, "ANSI escapes leaked into non-TTY output"


def test_no_color_env_disables_color(monkeypatch, tmp_path):
    """NO_COLOR=1 forces colour off even if stdout is a TTY."""
    from mcp_server.doctor_mcp import _colour_enabled

    monkeypatch.setenv("NO_COLOR", "1")
    assert _colour_enabled() is False


# --- run_mcp --copy ----------------------------------------------------


def test_run_mcp_copy_flag(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = run_mcp(json_output=False, copy_header=True)
    out = capsys.readouterr().out
    assert "please paste" in out
    assert isinstance(rc, int)


def test_run_mcp_subcommand_dispatch_with_copy(monkeypatch, capsys, tmp_path):
    """The doctor.run dispatcher honours --copy."""
    from mcp_server import doctor

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["cortex-doctor", "mcp", "--copy"])
    doctor.run()
    out = capsys.readouterr().out
    assert "please paste" in out


# --- skipped probes ----------------------------------------------------


def test_report_includes_skipped_handshake():
    """The MCP stdio handshake is explicitly declared 'I don't know'."""
    report = collect_mcp_report()
    assert any("stdio handshake" in s.get("name", "") for s in report.skipped), (
        "stdio handshake must be reported as skipped, not silently absent"
    )
    serialized = report.to_dict()
    assert "skipped" in serialized
    assert serialized["skipped"], "skipped list must be non-empty"


# --- check name uniqueness ---------------------------------------------


def test_all_check_names_unique():
    """No two checks share a name (would confuse Discord-paste readers)."""
    report = collect_mcp_report()
    names = [c.name for c in report.checks]
    assert len(names) == len(set(names)), f"duplicate names: {names}"
