"""Codex hook backend must match the MCP server for explicit URLs. source: ADR-0535"""

import os

import pytest

from mcp_server.hooks.entry import prepare_environment
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
