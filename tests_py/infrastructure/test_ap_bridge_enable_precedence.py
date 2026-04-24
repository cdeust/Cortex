"""Precedence tests for ``ap_bridge.is_enabled()``.

Contract (post-v3.14.2):
  1. Legacy env ``CORTEX_ENABLE_AP`` wins when set (explicit override).
  2. Else ``MemorySettings.AP_ENABLED`` (settable via
     ``CORTEX_MEMORY_AP_ENABLED`` in the MCP server env block).
  3. Hardcoded default is ``True`` — AP enrichment is on out of the box;
     users opt OUT to cut token / subprocess cost.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Each test starts with both flags unset; settings cache cleared."""
    monkeypatch.delenv("CORTEX_ENABLE_AP", raising=False)
    monkeypatch.delenv("CORTEX_MEMORY_AP_ENABLED", raising=False)
    from mcp_server.infrastructure import memory_config

    # MemorySettings is a BaseSettings singleton with lru_cache; drop it
    # so the next get_memory_settings() re-reads the env.
    memory_config.get_memory_settings.cache_clear()
    yield
    memory_config.get_memory_settings.cache_clear()


class TestDefault:
    def test_no_env_no_settings_override_defaults_on(self):
        """New contract: AP enrichment on by default."""
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is True


class TestLegacyEnvOverride:
    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE", "On"])
    def test_legacy_env_truthy_forces_on(self, monkeypatch, val):
        monkeypatch.setenv("CORTEX_ENABLE_AP", val)
        # Even with config saying off, legacy env wins.
        monkeypatch.setenv("CORTEX_MEMORY_AP_ENABLED", "0")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "FALSE", "Off"])
    def test_legacy_env_falsy_forces_off(self, monkeypatch, val):
        monkeypatch.setenv("CORTEX_ENABLE_AP", val)
        # Even with config saying on (default), legacy env wins.
        monkeypatch.setenv("CORTEX_MEMORY_AP_ENABLED", "1")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is False

    def test_legacy_env_empty_string_is_not_an_override(self, monkeypatch):
        """An empty string is "unset" — we fall through to config."""
        monkeypatch.setenv("CORTEX_ENABLE_AP", "")
        monkeypatch.setenv("CORTEX_MEMORY_AP_ENABLED", "0")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is False

    def test_legacy_env_garbage_falls_through_to_settings(self, monkeypatch):
        """Values outside the recognised set don't override — config wins."""
        monkeypatch.setenv("CORTEX_ENABLE_AP", "maybe")
        monkeypatch.setenv("CORTEX_MEMORY_AP_ENABLED", "0")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()
        from mcp_server.infrastructure.ap_bridge import is_enabled

        assert is_enabled() is False


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
