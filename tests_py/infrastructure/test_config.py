"""Tests for mcp_server.infrastructure.config."""

from pathlib import Path

from mcp_server.infrastructure.config import (
    CLAUDE_DIR,
    METHODOLOGY_DIR,
    PROFILES_PATH,
    SESSION_LOG_PATH,
    BRAIN_INDEX_PATH,
    MCP_CONNECTIONS_PATH,
)


class TestConfig:
    def test_all_paths_are_absolute(self):
        for p in [
            CLAUDE_DIR,
            METHODOLOGY_DIR,
            PROFILES_PATH,
            SESSION_LOG_PATH,
            BRAIN_INDEX_PATH,
            MCP_CONNECTIONS_PATH,
        ]:
            assert p.is_absolute()

    def test_claude_dir_is_dot_claude(self):
        assert CLAUDE_DIR == Path.home() / ".claude"

    def test_methodology_dir_under_claude(self):
        assert METHODOLOGY_DIR == CLAUDE_DIR / "methodology"

    def test_profiles_path(self):
        assert PROFILES_PATH == METHODOLOGY_DIR / "profiles.json"

    def test_session_log_path(self):
        assert SESSION_LOG_PATH == METHODOLOGY_DIR / "session-log.json"

    def test_brain_index_path(self):
        assert BRAIN_INDEX_PATH == CLAUDE_DIR / "brain-index.json"

    def test_mcp_connections_path(self):
        assert MCP_CONNECTIONS_PATH == METHODOLOGY_DIR / "mcp-connections.json"
