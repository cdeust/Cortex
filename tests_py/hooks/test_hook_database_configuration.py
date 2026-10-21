"""Hooks must preserve the configured store URL. source: ADR-1085"""

from unittest.mock import MagicMock

import pytest

from mcp_server.hooks.agent_briefing_query import _store
from mcp_server.infrastructure import memory_store
from mcp_server.hooks.entry import prepare_environment
from mcp_server.infrastructure.memory_config import get_memory_settings


def test_entry_promotes_namespaced_url_without_redirecting_to_default(tmp_path):
    environ = {"CORTEX_MEMORY_DATABASE_URL": "postgresql:///briefing_alias_test"}
    prepare_environment(environ, tmp_path / "absent-marker.json")
    assert environ["DATABASE_URL"] == "postgresql:///briefing_alias_test"


@pytest.mark.parametrize("backend", ["auto", "postgresql"])
@pytest.mark.parametrize("canonical", [None, "postgresql:///canonical_test"])
def test_direct_briefing_uses_settings_url_and_canonical_precedence(
    monkeypatch, canonical, backend
):
    """The briefing hook reaches PostgreSQL through the shared store
    (ADR-1112); the store resolves the same canonical-first URL."""
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", backend)
    monkeypatch.setenv(
        "CORTEX_MEMORY_DATABASE_URL", "postgresql:///briefing_alias_test"
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if canonical:
        monkeypatch.setenv("DATABASE_URL", canonical)
    get_memory_settings.cache_clear()
    memory_store.reset_shared_store()
    dialled: list[str] = []
    sentinel = MagicMock()
    monkeypatch.setattr(
        memory_store,
        "_try_pg_verbose",
        lambda url: dialled.append(url) or (sentinel, None),
    )
    try:
        assert _store() is sentinel
        assert dialled == [canonical or "postgresql:///briefing_alias_test"]
    finally:
        memory_store._shared_stores.clear()
        get_memory_settings.cache_clear()


@pytest.mark.parametrize("backend", ["auto", "postgresql"])
def test_entry_keeps_canonical_precedence_and_promotes_after_blank_normalization(
    tmp_path, backend
):
    environ = {
        "CORTEX_MEMORY_STORE_BACKEND": backend,
        "DATABASE_URL": "postgresql:///canonical_test",
        "CORTEX_MEMORY_DATABASE_URL": "postgresql:///alias_test",
    }
    prepare_environment(environ, tmp_path / "absent-marker.json")
    assert environ["DATABASE_URL"] == "postgresql:///canonical_test"
    environ["DATABASE_URL"] = "  "
    prepare_environment(environ, tmp_path / "absent-marker.json")
    assert environ["DATABASE_URL"] == "postgresql:///alias_test"


def test_sqlite_selection_does_not_promote_database_alias(tmp_path):
    environ = {
        "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
        "CORTEX_MEMORY_DATABASE_URL": "postgresql:///alias_test",
    }
    prepare_environment(environ, tmp_path / "absent-marker.json")
    assert "DATABASE_URL" not in environ
