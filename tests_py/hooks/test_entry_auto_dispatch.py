"""PR804 review4388465600: explicit auto must reach a usable hook backend."""

import importlib
import os
from pathlib import Path

import pytest

from mcp_server.hooks import auto_recall, entry, wiring
from mcp_server.infrastructure import db_connect, memory_config, memory_store
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture
def dispatch_hook(monkeypatch):
    observed = {}
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    monkeypatch.setattr(entry.sys, "argv", ["hook", "auto_recall"])
    monkeypatch.setattr(entry, "use_utf8_output", lambda: None)
    monkeypatch.setattr(wiring, "wire_composition_root", lambda: None)
    monkeypatch.setattr(entry, "read_event_or_exit", lambda name: "{}")
    monkeypatch.setattr(entry, "derive_events", lambda *args: ([{}], "test", None))
    # Restore the module constant after simulating the fresh dispatch import.
    monkeypatch.setattr(auto_recall, "_DATABASE_URL", auto_recall._DATABASE_URL)

    def capture(*args):
        hook = importlib.reload(auto_recall)
        observed["sqlite"] = hook._backend_is_sqlite()
        observed["url"] = hook._DATABASE_URL
        if not observed["sqlite"]:
            observed["connection"] = hook._connect()
        return 0

    monkeypatch.setattr(entry, "run_all", capture)

    def run(entry_point):
        if entry_point == "launcher":
            import launcher_backend

            launcher_backend.apply()
            capture()
            return observed
        with pytest.raises(SystemExit) as stopped:
            entry.main()
        assert stopped.value.code == 0
        return observed

    return run


@pytest.mark.parametrize("entry_point", ["wheel", "launcher"])
@pytest.mark.parametrize("sqlite", [True, False])
def test_engine_selected_auto_backend_reaches_hook(
    entry_point, sqlite, tmp_path, monkeypatch, dispatch_hook
):
    monkeypatch.setenv("CORTEX_RUNTIME", "cowork" if entry_point == "wheel" else "cli")
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "auto")
    for key in ("DATABASE_URL", "CORTEX_MEMORY_DATABASE_URL", "CORTEX_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_DATABASE_URL", raising=False)
    local = SqliteMemoryStore(str(tmp_path / "auto.sqlite"))
    selected_url = "postgresql://127.0.0.1/operator_selected_test"
    selected = local if sqlite else object()
    connection = object()
    monkeypatch.setattr(memory_store, "get_shared_store", lambda: selected)
    monkeypatch.setattr(
        memory_config.get_memory_settings(), "DATABASE_URL", selected_url
    )
    monkeypatch.setattr(db_connect, "pg_connect", lambda *args, **kwargs: connection)
    try:
        observed = dispatch_hook(entry_point)
        assert observed["sqlite"] is sqlite
        assert os.environ["CORTEX_MEMORY_STORE_BACKEND"] == (
            "sqlite" if sqlite else "postgresql"
        )
        if not sqlite:
            assert observed["url"] == selected_url
            assert observed["connection"] is connection
    finally:
        local.close()
