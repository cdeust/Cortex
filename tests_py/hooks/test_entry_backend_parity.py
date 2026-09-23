"""Codex hook backend must match the MCP server for explicit URLs. source: ADR-0535"""

import os

import pytest

from mcp_server.hooks.entry import prepare_environment, resolve_auto_backend
from mcp_server.infrastructure import memory_store
from mcp_server.infrastructure.backend_marker import apply_backend_resolution
from mcp_server.infrastructure.memory_config import get_memory_settings


@pytest.mark.parametrize("url_key", ["DATABASE_URL", "CORTEX_MEMORY_DATABASE_URL"])
def test_explicit_postgres_target_never_falls_back_to_sqlite(
    tmp_path, monkeypatch, url_key
):
    url = "postgresql:///unavailable_cortex_test"
    monkeypatch.setenv("CORTEX_RUNTIME", "cowork")
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv(url_key, url)
    monkeypatch.delenv("CORTEX_MEMORY_STORE_BACKEND", raising=False)
    monkeypatch.delenv("CORTEX_BACKEND", raising=False)
    other = (
        "DATABASE_URL" if url_key != "DATABASE_URL" else "CORTEX_MEMORY_DATABASE_URL"
    )
    monkeypatch.delenv(other, raising=False)
    monkeypatch.setattr(memory_store, "_try_pg_verbose", lambda _url: (None, "offline"))
    memory_store.reset_shared_store()
    get_memory_settings.cache_clear()
    try:
        prepare_environment(os.environ, tmp_path / "absent-marker.json")
        resolve_auto_backend(os.environ)
        assert os.environ["DATABASE_URL"] == url
        with pytest.raises(RuntimeError, match="explicit DATABASE_URL unreachable"):
            memory_store.get_shared_store()
    finally:
        memory_store.reset_shared_store()
        get_memory_settings.cache_clear()


def test_mcp_namespaced_postgres_target_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_RUNTIME", "cowork")
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CORTEX_MEMORY_DATABASE_URL", "postgresql:///operator_db")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CORTEX_MEMORY_STORE_BACKEND", raising=False)
    monkeypatch.setattr(memory_store, "_try_pg_verbose", lambda _url: (None, "offline"))
    memory_store.reset_shared_store()
    get_memory_settings.cache_clear()
    try:
        apply_backend_resolution(os.environ, tmp_path / "absent-marker.json")
        with pytest.raises(RuntimeError, match="explicit DATABASE_URL unreachable"):
            memory_store.get_shared_store()
    finally:
        memory_store.reset_shared_store()
        get_memory_settings.cache_clear()


@pytest.mark.parametrize(
    "environ",
    [
        {"CORTEX_RUNTIME": "cli"},
        {"CORTEX_RUNTIME": "cowork", "CORTEX_MEMORY_STORE_BACKEND": "sqlite"},
        {"CORTEX_RUNTIME": "cowork", "CORTEX_MEMORY_STORE_BACKEND": "postgresql"},
        {"CORTEX_RUNTIME": "cowork", "DATABASE_URL": "postgresql:///operator_db"},
        {
            "CORTEX_RUNTIME": "cowork",
            "CORTEX_MEMORY_DATABASE_URL": "postgresql:///operator_db",
        },
    ],
)
def test_resolved_backend_skips_auto_store_probe(environ, monkeypatch):
    def unexpected_store():
        pytest.fail("configured backend must not run auto store selection")

    monkeypatch.setattr(memory_store, "get_shared_store", unexpected_store)
    original = environ.copy()
    resolve_auto_backend(environ)
    assert environ == original
