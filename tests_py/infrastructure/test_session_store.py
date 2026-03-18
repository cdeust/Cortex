"""Tests for mcp_server.infrastructure.session_store — ported from session-store.test.js."""

from unittest.mock import patch

from mcp_server.infrastructure.session_store import load_session_log, save_session_log


class TestLoadSessionLog:
    def test_returns_valid_structure(self):
        log = load_session_log()
        assert log is not None
        assert isinstance(log.get("sessions"), list)


class TestSaveSessionLog:
    def test_saves_without_error(self, tmp_path):
        path = tmp_path / "session-log.json"
        with patch("mcp_server.infrastructure.session_store.SESSION_LOG_PATH", path):
            log = {"sessions": []}
            save_session_log(log)
