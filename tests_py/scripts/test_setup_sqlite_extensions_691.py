"""Setup rejects missing SQLite extension support before installing (issue #691)."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests_py.scripts.test_setup_py_backend_skip import _load_setup_module


def test_sqlite_setup_stops_before_install(monkeypatch, capsys):
    mod = _load_setup_module(monkeypatch, "sqlite")
    monkeypatch.setitem(sys.modules, "sqlite3", SimpleNamespace(Connection=object))
    monkeypatch.setattr(mod, "_use_utf8_output", lambda: None)
    install = Mock()
    monkeypatch.setattr(mod, "install_deps", install)

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 1
    install.assert_not_called()
    output = capsys.readouterr().out
    assert "enable_load_extension" in output
    assert "Homebrew" in output
    assert "uv-managed" in output
    assert "Cortex setup complete!" not in output


def test_extension_capable_python_passes_preflight(monkeypatch):
    mod = _load_setup_module(monkeypatch, "sqlite")
    connection = SimpleNamespace(enable_load_extension=lambda enabled: None)
    monkeypatch.setitem(
        sys.modules, "sqlite3", SimpleNamespace(Connection=connection)
    )
    mod.setup_sqlite.check_sqlite_extension_loading(mod.fail)


def test_postgres_setup_does_not_require_sqlite_extensions(monkeypatch):
    mod = _load_setup_module(monkeypatch, "postgresql")
    for name in (
        "_use_utf8_output",
        "check_python",
        "check_postgresql",
        "install_deps",
        "setup_database",
        "cache_embedding_model",
        "verify",
    ):
        monkeypatch.setattr(mod, name, Mock())
    preflight = Mock()
    monkeypatch.setattr(mod.setup_sqlite, "check_sqlite_extension_loading", preflight)
    mod.main()
    preflight.assert_not_called()
