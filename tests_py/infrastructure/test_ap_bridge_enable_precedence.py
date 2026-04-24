"""Tests for ``ap_bridge.is_enabled()``.

Contract (post-v3.14.2):
  * Single source of truth: ``MemorySettings.AP_ENABLED`` (settable via
    ``CORTEX_MEMORY_AP_ENABLED`` in the MCP server env block).
  * Default is ``True`` — AP enrichment is on out of the box; users opt
    OUT to cut token / subprocess cost.
  * The legacy ``CORTEX_ENABLE_AP`` env var was removed; setting it has
    no effect.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Each test starts with a clean env; settings cache cleared."""
    monkeypatch.delenv("CORTEX_ENABLE_AP", raising=False)
    monkeypatch.delenv("CORTEX_MEMORY_AP_ENABLED", raising=False)
    from mcp_server.infrastructure import memory_config

    # MemorySettings is a BaseSettings singleton with lru_cache; drop it
    # so the next get_memory_settings() re-reads the env.
    memory_config.get_memory_settings.cache_clear()
    yield
    memory_config.get_memory_settings.cache_clear()


class TestDefault:
    def test_no_env_defaults_on(self):
        """AP enrichment on by default — L6 depth out of the box."""
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is True


class TestMCPConfigOverride:
    def test_memory_setting_false_turns_off(self, monkeypatch):
        """The opt-out path users take to cut token cost."""
        monkeypatch.setenv("CORTEX_MEMORY_AP_ENABLED", "0")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is False

    def test_memory_setting_true_explicit_opt_in(self, monkeypatch):
        monkeypatch.setenv("CORTEX_MEMORY_AP_ENABLED", "1")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is True


class TestLegacyEnvRemoved:
    """The legacy ``CORTEX_ENABLE_AP`` env var was removed in v3.14.2.
    Setting it must not influence is_enabled() at all — only
    ``CORTEX_MEMORY_AP_ENABLED`` / ``MemorySettings.AP_ENABLED`` do."""

    def test_legacy_env_has_no_effect_when_memory_setting_off(
        self, monkeypatch
    ):
        monkeypatch.setenv("CORTEX_ENABLE_AP", "1")  # used to force on
        monkeypatch.setenv("CORTEX_MEMORY_AP_ENABLED", "0")  # real flag says off
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()
        from mcp_server.infrastructure.ap_bridge import is_enabled

        # Memory setting wins — legacy env is inert.
        assert is_enabled() is False

    def test_legacy_env_has_no_effect_on_default(self, monkeypatch):
        """Legacy env set to "off" must not override the on-by-default
        contract. Only CORTEX_MEMORY_AP_ENABLED can turn it off now."""
        monkeypatch.setenv("CORTEX_ENABLE_AP", "0")
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is True
